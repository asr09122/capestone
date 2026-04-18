"""Inventory tools — graph nodes call these directly."""
import sqlite3
from datetime import datetime, timedelta

from langchain_core.tools import tool
from app.core.config import get_settings


def _db():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def get_inventory(seller_id: int, product_id: int) -> dict:
    """Get stock_qty, cost_price, selling_price for a seller-product pair. Returns {} if not found."""
    with _db() as conn:
        row = conn.execute(
            "SELECT stock_qty, cost_price, selling_price FROM inventory WHERE seller_id=? AND product_id=?",
            (seller_id, product_id),
        ).fetchone()
    return dict(row) if row else {}


@tool
def update_stock(seller_id: int, product_id: int, qty_change: int) -> dict:
    """Change stock by qty_change (negative = sale, positive = restock). Returns new_stock_qty."""
    with _db() as conn:
        row = conn.execute(
            "SELECT stock_qty FROM inventory WHERE seller_id=? AND product_id=?",
            (seller_id, product_id),
        ).fetchone()
        if not row:
            raise ValueError(f"No inventory for seller={seller_id} product={product_id}")
        new_qty = int(row["stock_qty"]) + qty_change
        if new_qty < 0:
            raise ValueError(f"Not enough stock: have {row['stock_qty']}, requested change={qty_change}")
        conn.execute(
            "UPDATE inventory SET stock_qty=? WHERE seller_id=? AND product_id=?",
            (new_qty, seller_id, product_id),
        )
        conn.commit()
    return {"new_stock_qty": new_qty}


@tool
def update_selling_price(seller_id: int, product_id: int, price: float) -> dict:
    """Sync selling_price to the latest billed price."""
    with _db() as conn:
        conn.execute(
            "UPDATE inventory SET selling_price=? WHERE seller_id=? AND product_id=?",
            (price, seller_id, product_id),
        )
        conn.commit()
    return {"selling_price": price}


@tool
def update_cost_price(seller_id: int, product_id: int, cost: float) -> dict:
    """Update cost_price after a transfer is approved (weighted avg procurement cost)."""
    with _db() as conn:
        conn.execute(
            "UPDATE inventory SET cost_price=? WHERE seller_id=? AND product_id=?",
            (cost, seller_id, product_id),
        )
        conn.commit()
    return {"cost_price": cost}


@tool
def record_transaction(seller_id: int, product_id: int, qty: int, price: float,
                       demand_id: int = None, status: str = "completed") -> dict:
    """Insert a transaction record. Returns txn_id."""
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (seller_id, product_id, qty, agreed_price, status, demand_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (seller_id, product_id, qty, price, status, demand_id,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    return {"txn_id": cur.lastrowid}


@tool
def upsert_profit(seller_id: int, revenue: float, cost: float) -> dict:
    """Add revenue and cost to this month's profit row. Creates the row if it doesn't exist."""
    month = datetime.now().strftime("%Y-%m")
    profit = round(revenue - cost, 2)
    with _db() as conn:
        existing = conn.execute(
            "SELECT profit_id FROM profits WHERE seller_id=? AND month=?",
            (seller_id, month),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE profits SET revenue=revenue+?, cost=cost+?, profit=profit+? "
                "WHERE seller_id=? AND month=?",
                (revenue, cost, profit, seller_id, month),
            )
        else:
            conn.execute(
                "INSERT INTO profits (seller_id, month, revenue, cost, profit) VALUES (?,?,?,?,?)",
                (seller_id, month, revenue, cost, profit),
            )
        conn.commit()
    return {"seller_id": seller_id, "month": month}


@tool
def get_avg_price(seller_id: int, product_id: int, days: int = 30) -> float:
    """Get the average agreed_price from completed transactions over the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as conn:
        row = conn.execute(
            "SELECT AVG(agreed_price) as avg FROM transactions "
            "WHERE seller_id=? AND product_id=? AND status='completed' AND created_at>=?",
            (seller_id, product_id, cutoff),
        ).fetchone()
    return round(float(row["avg"] or 0.0), 2)


@tool
def get_sales_stats(seller_id: int, product_id: int, days: int = 30) -> dict:
    """Get total_qty, daily_avg, and 7-day threshold from completed transactions."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(qty),0) as total FROM transactions "
            "WHERE seller_id=? AND product_id=? AND status='completed' AND created_at>=?",
            (seller_id, product_id, cutoff),
        ).fetchone()
    total = int(row["total"])
    daily_avg = round(total / days, 2)
    return {"total_qty": total, "daily_avg": daily_avg, "threshold": round(daily_avg * 7, 2)}


@tool
def create_demand(seller_id: int, product_id: int, qty_needed: int) -> dict:
    """Create or update an open demand post. Returns demand_id."""
    with _db() as conn:
        existing = conn.execute(
            "SELECT demand_id, qty_needed FROM demand_posts "
            "WHERE seller_id=? AND product_id=? AND status='open'",
            (seller_id, product_id),
        ).fetchone()
        if existing:
            new_qty = max(int(existing["qty_needed"]), qty_needed)
            conn.execute(
                "UPDATE demand_posts SET qty_needed=? WHERE demand_id=?",
                (new_qty, existing["demand_id"]),
            )
            conn.commit()
            return {"demand_id": existing["demand_id"], "qty_needed": new_qty}
        cur = conn.execute(
            "INSERT INTO demand_posts (seller_id, product_id, qty_needed, status, created_at) "
            "VALUES (?,?,?,'open',?)",
            (seller_id, product_id, qty_needed, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    return {"demand_id": cur.lastrowid, "qty_needed": qty_needed}


@tool
def find_suppliers(product_id: int, exclude_seller_id: int, qty_needed: int, target_price: float = 0.0) -> list:
    """Find all sellers with stock for a product, ranked by price closeness to target_price."""
    with _db() as conn:
        rows = conn.execute(
            """SELECT s.seller_id, s.name as seller_name, s.location, s.sector,
                      i.stock_qty, i.cost_price, i.selling_price
               FROM inventory i JOIN sellers s ON i.seller_id=s.seller_id
               WHERE i.product_id=? AND i.stock_qty>0 AND i.seller_id!=?
               ORDER BY i.selling_price ASC""",
            (product_id, exclude_seller_id),
        ).fetchall()
    candidates = []
    for r in rows:
        d = dict(r)
        d["fulfillable_qty"] = min(int(d["stock_qty"]), qty_needed)
        d["full_cover"] = int(d["stock_qty"]) >= qty_needed
        d["price_delta"] = round(float(d["selling_price"]) - float(target_price), 2)
        d["total_cost"] = round(float(d["selling_price"]) * d["fulfillable_qty"], 2)
        candidates.append(d)
    if target_price > 0:
        candidates.sort(key=lambda c: (abs(c["price_delta"]), c["selling_price"]))
    return candidates


@tool
def create_transfer(from_seller_id: int, to_seller_id: int, product_id: int,
                    qty: int, transfer_price: float, demand_id: int = None) -> dict:
    """Create a pending transfer request. Inventory is NOT moved until supplier approves."""
    if qty <= 0 or transfer_price <= 0 or from_seller_id == to_seller_id:
        raise ValueError("Invalid transfer parameters")
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO transfers (from_seller_id, to_seller_id, product_id, qty, transfer_price, status, demand_id) "
            "VALUES (?,?,?,?,?,'pending',?)",
            (from_seller_id, to_seller_id, product_id, qty, transfer_price, demand_id),
        )
        conn.commit()
    return {"transfer_id": cur.lastrowid, "status": "pending"}


# ── plain helpers (not tools) used by routes that need raw data ───────────────

def get_inventory_raw(seller_id: int, product_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT stock_qty, cost_price, selling_price FROM inventory WHERE seller_id=? AND product_id=?",
            (seller_id, product_id),
        ).fetchone()
    return dict(row) if row else None
