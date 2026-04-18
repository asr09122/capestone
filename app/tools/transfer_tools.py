"""Transfer tools — inter-seller stock matching and transfer management."""

import sqlite3

from langchain_core.tools import tool

from app.core.config import get_settings


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def find_sellers_with_stock(
    product_id: int, qty_needed: int, exclude_seller_id: int = 0, target_price: float = 0.0
) -> list:
    """Find sellers who have ANY stock for a given product, ranked by price closeness to target_price.

    Returns candidates with partial fulfillment info:
      - seller_id, seller_name, location, sector
      - stock_qty, cost_price, selling_price, fulfillable_qty, full_cover, price_delta
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.seller_id, s.name AS seller_name, s.location, s.sector,
                   i.stock_qty, i.cost_price, i.selling_price
            FROM inventory i
            JOIN sellers s ON i.seller_id = s.seller_id
            WHERE i.product_id = ?
              AND i.stock_qty > 0
              AND i.seller_id != ?
            ORDER BY i.selling_price ASC
            """,
            (product_id, exclude_seller_id),
        ).fetchall()
    candidates = []
    for r in rows:
        d = dict(r)
        d["fulfillable_qty"] = min(int(d["stock_qty"]), qty_needed)
        d["full_cover"] = int(d["stock_qty"]) >= qty_needed
        d["price_delta"] = round(float(d["selling_price"]) - float(target_price), 2)
        candidates.append(d)
    if target_price > 0:
        candidates.sort(key=lambda c: (abs(c["price_delta"]), c["selling_price"]))
    return candidates


@tool
def create_transfer(
    from_seller_id: int,
    to_seller_id: int,
    product_id: int,
    qty: int,
    transfer_price: float,
) -> dict:
    """Create a pending transfer record between two sellers.

    Does NOT update inventory — inventory is updated only after human approval.
    Returns: {transfer_id, from_seller_id, to_seller_id, product_id, qty, transfer_price, status}
    """
    if qty <= 0:
        raise ValueError("qty must be positive")
    if transfer_price <= 0:
        raise ValueError("transfer_price must be positive")
    if from_seller_id == to_seller_id:
        raise ValueError("from_seller_id and to_seller_id must differ")

    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO transfers (from_seller_id, to_seller_id, product_id, qty, transfer_price, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (from_seller_id, to_seller_id, product_id, qty, transfer_price),
        )
        transfer_id = cur.lastrowid
        conn.commit()

    return {
        "transfer_id": transfer_id,
        "from_seller_id": from_seller_id,
        "to_seller_id": to_seller_id,
        "product_id": product_id,
        "qty": qty,
        "transfer_price": transfer_price,
        "status": "pending",
    }


# —— Non-tool helpers for workflow use —————————————————————————————————————————


def find_sellers_with_stock_raw(
    product_id: int, qty_needed: int, exclude_seller_id: int = 0
) -> list[dict]:
    """Find sellers with sufficient stock, sorted by cost_price (cheapest first)."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.seller_id, s.name AS seller_name, s.location, s.sector,
                   i.stock_qty, i.cost_price, i.selling_price
            FROM inventory i
            JOIN sellers s ON i.seller_id = s.seller_id
            WHERE i.product_id = ?
              AND i.stock_qty >= ?
              AND i.seller_id != ?
            ORDER BY i.selling_price ASC
            """,
            (product_id, qty_needed, exclude_seller_id),
        ).fetchall()
    return [dict(r) for r in rows]


def create_transfer_raw(
    from_seller_id: int,
    to_seller_id: int,
    product_id: int,
    qty: int,
    transfer_price: float,
) -> dict:
    if qty <= 0:
        raise ValueError("qty must be positive")
    if transfer_price <= 0:
        raise ValueError("transfer_price must be positive")
    if from_seller_id == to_seller_id:
        raise ValueError("from_seller_id and to_seller_id must differ")
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO transfers (from_seller_id, to_seller_id, product_id, qty, transfer_price, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (from_seller_id, to_seller_id, product_id, qty, transfer_price),
        )
        transfer_id = cur.lastrowid
        conn.commit()
    return {"transfer_id": transfer_id, "status": "pending"}


def complete_transfer(transfer_id: int) -> None:
    """Mark a transfer as completed."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE transfers SET status = 'completed' WHERE transfer_id = ?",
            (transfer_id,),
        )
        conn.commit()


def split_fulfillment_plan(
    product_id: int, qty_needed: int, exclude_seller_id: int = 0
) -> dict:
    """Build a multi-seller split plan when no single seller can fulfil qty_needed.

    Greedy: take from the cheapest seller first, then the next, until covered.
    Returns:
      {
        "picks":          [{seller_id, seller_name, qty, unit_price}, ...],
        "total_qty":      covered units,
        "avg_unit_price": weighted-avg â‚¹/unit,
        "fully_covered":  True/False,
      }
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.seller_id, s.name AS seller_name,
                   i.stock_qty, i.selling_price
            FROM inventory i JOIN sellers s ON i.seller_id = s.seller_id
            WHERE i.product_id = ? AND i.stock_qty > 0 AND i.seller_id != ?
            ORDER BY i.selling_price ASC
            """,
            (product_id, exclude_seller_id),
        ).fetchall()

    remaining = qty_needed
    picks: list[dict] = []
    total_cost = 0.0
    for r in rows:
        if remaining <= 0:
            break
        take = min(int(r["stock_qty"]), remaining)
        picks.append({
            "seller_id":   int(r["seller_id"]),
            "seller_name": r["seller_name"],
            "qty":         take,
            "unit_price":  float(r["selling_price"]),
        })
        total_cost += take * float(r["selling_price"])
        remaining -= take

    covered = qty_needed - remaining
    avg_price = round(total_cost / covered, 2) if covered > 0 else 0.0
    return {
        "picks":          picks,
        "total_qty":      covered,
        "avg_unit_price": avg_price,
        "fully_covered":  remaining == 0,
    }


def reject_transfer(transfer_id: int) -> None:
    """Mark a pending transfer as rejected.

    Only transitions pending â†’ rejected. A transfer that has already moved to
    'countered' (active negotiation) or 'completed' is left untouched so a
    parallel workflow rejection cannot clobber an ongoing negotiation.
    """
    with _get_conn() as conn:
        conn.execute(
            "UPDATE transfers SET status = 'rejected' "
            "WHERE transfer_id = ? AND status = 'pending'",
            (transfer_id,),
        )
        conn.commit()
