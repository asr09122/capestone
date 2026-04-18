"""Input validation and guardrails for RetailFlow AI.

All checks raise ValueError with a descriptive message on failure.
"""
import re


# ── SQL guardrail ─────────────────────────────────────────────────────────────

_DISALLOWED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE|UPSERT)\b",
    re.IGNORECASE,
)


def validate_sql_query(query: str) -> None:
    """Ensure query contains only SELECT statements.

    Raises ValueError for any data-modification keyword.
    """
    if _DISALLOWED_SQL.search(query):
        raise ValueError(
            "Only SELECT queries are allowed. Modification operations (INSERT, UPDATE, "
            "DELETE, DROP, etc.) are blocked."
        )


# ── Pricing guardrails ────────────────────────────────────────────────────────

def validate_pricing(price: float, avg_price: float, threshold: float = 0.20) -> bool:
    """Check if a price deviates anomalously from the historical average.

    Returns True if anomaly detected (deviation > threshold).
    threshold=0.20 means >20% deviation flags an anomaly.
    """
    if avg_price <= 0:
        return False
    deviation = abs(price - avg_price) / avg_price
    return deviation > threshold


def validate_billing_input(
    seller_id: int,
    product_id: int,
    quantity: int,
    price: float,
) -> None:
    """Validate billing request inputs."""
    if not isinstance(seller_id, int) or seller_id <= 0:
        raise ValueError("seller_id must be a positive integer")
    if not isinstance(product_id, int) or product_id <= 0:
        raise ValueError("product_id must be a positive integer")
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    if price <= 0:
        raise ValueError("price must be a positive number")


def validate_demand_input(seller_id: int, product_id: int, quantity: int) -> None:
    """Validate manual demand request inputs."""
    if not isinstance(seller_id, int) or seller_id <= 0:
        raise ValueError("seller_id must be a positive integer")
    if not isinstance(product_id, int) or product_id <= 0:
        raise ValueError("product_id must be a positive integer")
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive integer")


def validate_transfer_feasibility(from_stock: int, qty: int) -> None:
    """Ensure the source seller has enough stock to fulfil the transfer."""
    if from_stock < qty:
        raise ValueError(
            f"Insufficient stock for transfer: available={from_stock}, requested={qty}"
        )


def validate_price_floor(price: float, cost_price: float) -> None:
    """Ensure no transaction happens below cost price."""
    floor = cost_price * 1.03  # 3% minimum margin
    if price < floor:
        raise ValueError(
            f"Price ₹{price:.2f} is below the minimum floor ₹{floor:.2f} "
            f"(cost ₹{cost_price:.2f} + 3% minimum margin)"
        )
