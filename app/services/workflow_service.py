"""Transfer approval logic and profit history — used by routes, not the graph."""
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DemandPost, Inventory, Product, Profit, Seller, Transaction, Transfer, User

MAX_NEGOTIATION_ROUNDS = 5


# ── Role helpers (used at startup) ────────────────────────────────────────────

def normalize_role(role, seller_id):
    if role == "admin": return "admin"
    return "seller" if seller_id else "admin"


def normalize_existing_roles(session: Session) -> int:
    rows = session.execute(select(User).where(User.role != "admin")).scalars().all()
    changed = 0
    for user in rows:
        new = normalize_role(user.role, user.seller_id)
        if user.role != new:
            user.role = new
            changed += 1
    return changed


# ── Transfer serialization ────────────────────────────────────────────────────

def serialize_transfer(t: Transfer, session: Session) -> dict:
    product     = session.get(Product, t.product_id)
    from_seller = session.get(Seller, t.from_seller_id)
    to_seller   = session.get(Seller, t.to_seller_id)
    return {
        "transfer_id":      t.transfer_id,
        "from_seller_id":   t.from_seller_id,
        "to_seller_id":     t.to_seller_id,
        "product_id":       t.product_id,
        "product_name":     product.name if product else f"Product #{t.product_id}",
        "from_seller_name": from_seller.name if from_seller else f"Seller #{t.from_seller_id}",
        "to_seller_name":   to_seller.name if to_seller else f"Seller #{t.to_seller_id}",
        "qty":              t.qty,
        "transfer_price":   t.transfer_price,
        "counter_price":    t.counter_price,
        "status":           t.status,
        "negotiation_rounds": t.negotiation_rounds,
        "demand_id":        t.demand_id,
        "total_value":      round(float(t.qty) * float(t.transfer_price), 2),
    }


def list_transfers(session: Session, *, seller_id: int, perspective: str) -> list:
    if perspective == "incoming":
        stmt = select(Transfer).where(Transfer.from_seller_id == seller_id, Transfer.status == "pending")
    elif perspective == "outgoing":
        stmt = select(Transfer).where(Transfer.to_seller_id == seller_id, Transfer.status == "pending")
    elif perspective == "countered":
        stmt = select(Transfer).where(Transfer.to_seller_id == seller_id, Transfer.status == "countered")
    else:
        raise ValueError(f"Unknown perspective: {perspective}")
    transfers = session.execute(stmt.order_by(Transfer.transfer_id.desc())).scalars()
    return [serialize_transfer(t, session) for t in transfers]


# ── Transfer state machine ────────────────────────────────────────────────────

def approve_transfer(session: Session, transfer_id: int) -> dict:
    t = session.get(Transfer, transfer_id)
    if not t: raise ValueError("Transfer not found")
    if t.status != "pending": raise ValueError(f"Transfer is '{t.status}', not pending")

    supplier_inv = session.execute(
        select(Inventory).where(Inventory.seller_id == t.from_seller_id, Inventory.product_id == t.product_id)
    ).scalar_one_or_none()
    buyer_inv = session.execute(
        select(Inventory).where(Inventory.seller_id == t.to_seller_id, Inventory.product_id == t.product_id)
    ).scalar_one_or_none()

    if not supplier_inv or supplier_inv.stock_qty < t.qty:
        raise ValueError(f"Supplier has {getattr(supplier_inv, 'stock_qty', 0)} units, need {t.qty}")

    # move stock
    supplier_inv.stock_qty -= t.qty
    buyer_inv.stock_qty    += t.qty

    # update buyer's cost_price to weighted average
    existing = int(buyer_inv.stock_qty - t.qty)  # stock before this transfer
    old_cost = float(buyer_inv.cost_price or t.transfer_price)
    total_units = existing + t.qty
    new_cost = round((existing * old_cost + t.qty * float(t.transfer_price)) / total_units, 2)
    buyer_inv.cost_price = new_cost

    # below-cost warning: buying price exceeds current selling price
    selling_price_now = float(buyer_inv.selling_price or 0)
    below_cost_warning = selling_price_now > 0 and selling_price_now < new_cost
    below_cost_message = (
        f"Warning: Your new cost (Rs. {new_cost:.2f}/unit) exceeds your selling price "
        f"(Rs. {selling_price_now:.2f}/unit). Consider increasing your selling price to avoid losses."
        if below_cost_warning else None
    )

    t.status = "completed"
    session.flush()

    # profits
    supplier_revenue = round(float(t.transfer_price) * t.qty, 2)
    supplier_cost    = round(float(supplier_inv.cost_price) * t.qty, 2)
    _upsert_profit(session, t.from_seller_id, supplier_revenue, supplier_cost)
    _upsert_profit(session, t.to_seller_id, 0.0, supplier_revenue)

    # transaction record
    session.add(Transaction(
        seller_id=t.from_seller_id, product_id=t.product_id,
        qty=t.qty, agreed_price=t.transfer_price, status="completed",
        demand_id=t.demand_id, negotiation_rounds=t.negotiation_rounds,
    ))

    # close demand if linked
    if t.demand_id:
        demand = session.get(DemandPost, t.demand_id)
        if demand: demand.status = "fulfilled"

    session.flush()
    result = serialize_transfer(t, session)
    result["new_cost_price"] = new_cost
    result["below_cost_warning"] = below_cost_warning
    result["below_cost_message"] = below_cost_message
    return result


def reject_transfer(session: Session, transfer_id: int, close_demand: bool = False) -> dict:
    t = session.get(Transfer, transfer_id)
    if not t: raise ValueError("Transfer not found")
    t.status = "rejected"
    if close_demand and t.demand_id:
        demand = session.get(DemandPost, t.demand_id)
        if demand: demand.status = "cancelled"
    session.flush()
    return serialize_transfer(t, session)


def counter_transfer(session: Session, transfer_id: int, counter_price: float) -> dict:
    t = session.get(Transfer, transfer_id)
    if not t: raise ValueError("Transfer not found")
    if t.status != "pending": raise ValueError(f"Cannot counter — transfer is '{t.status}'")
    rounds = int(t.negotiation_rounds or 1) + 1
    if rounds > MAX_NEGOTIATION_ROUNDS: raise ValueError(f"Max {MAX_NEGOTIATION_ROUNDS} rounds reached")
    t.counter_price = counter_price
    t.negotiation_rounds = rounds
    t.status = "countered"
    session.flush()
    return serialize_transfer(t, session)


def accept_counter(session: Session, transfer_id: int) -> dict:
    t = session.get(Transfer, transfer_id)
    if not t: raise ValueError("Transfer not found")
    if t.status != "countered": raise ValueError(f"Transfer is '{t.status}', not countered")
    if not t.counter_price: raise ValueError("No counter price set")
    t.transfer_price = t.counter_price
    t.counter_price = None
    t.status = "pending"
    session.flush()
    return serialize_transfer(t, session)


# ── Profit history (used by ML agent) ────────────────────────────────────────

def list_profit_history(session: Session, seller_id: int) -> list:
    rows = session.execute(
        select(Profit).where(Profit.seller_id == seller_id).order_by(Profit.month.asc())
    ).scalars()
    return [{"month": r.month, "revenue": r.revenue, "cost": r.cost, "profit": r.profit} for r in rows]


# ── Internal helper ───────────────────────────────────────────────────────────

def _upsert_profit(session: Session, seller_id: int, revenue: float, cost: float):
    month = datetime.now().strftime("%Y-%m")
    profit = session.execute(
        select(Profit).where(Profit.seller_id == seller_id, Profit.month == month)
    ).scalar_one_or_none()
    delta = round(revenue - cost, 2)
    if profit:
        profit.revenue = round(profit.revenue + revenue, 2)
        profit.cost    = round(profit.cost + cost, 2)
        profit.profit  = round(profit.profit + delta, 2)
    else:
        session.add(Profit(seller_id=seller_id, month=month,
                           revenue=round(revenue, 2), cost=round(cost, 2), profit=delta))
    session.flush()
