"""RetailFlow AI MCP server."""
from datetime import datetime
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func, select, text

from app.agents.ml_agent import run_profit_prediction_agent
from app.db.database import session_scope
from app.db.models import DemandPost, Inventory, Product, Profit, Seller, Transfer
from app.guardrails.validators import validate_sql_query
from app.services.workflow_service import list_profit_history, list_transfers
from app.tools.inventory_tools import (
    find_suppliers as find_suppliers_tool,
    get_inventory_raw,
    get_avg_price,
    get_sales_stats,
)

mcp = FastMCP(
    name="RetailFlow AI",
    instructions=(
        "MCP tools for RetailFlow AI. Use these for inventory, demand, transfer, "
        "profit, and knowledge-base tasks. All monetary values are in INR (₹)."
    ),
)


@mcp.tool()
def get_inventory(seller_id: int, product_id: int) -> dict:
    """Get stock_qty, cost_price, selling_price for a seller-product pair."""
    return get_inventory_raw(seller_id, product_id) or {}


@mcp.tool()
def list_inventory(seller_id: int) -> list:
    """List all inventory items for a seller with product names."""
    with session_scope() as session:
        rows = session.execute(
            select(Inventory, Product)
            .join(Product, Inventory.product_id == Product.product_id)
            .where(Inventory.seller_id == seller_id)
            .order_by(Product.category, Product.name)
        ).all()
        return [
            {
                "product_id": p.product_id, "product_name": p.name, "category": p.category,
                "stock_qty": i.stock_qty, "cost_price": i.cost_price, "selling_price": i.selling_price,
            }
            for i, p in rows
        ]


@mcp.tool()
def get_recent_sales(seller_id: int, product_id: int, days: int = 30) -> dict:
    """Get total_qty, daily_avg, and 7-day threshold from completed transactions."""
    return get_sales_stats.invoke({"seller_id": seller_id, "product_id": product_id, "days": days})


@mcp.tool()
def get_avg_transaction_price(seller_id: int, product_id: int, days: int = 30) -> float:
    """Get the 30-day average agreed_price for a seller-product pair."""
    return get_avg_price.invoke({"seller_id": seller_id, "product_id": product_id, "days": days})


@mcp.tool()
def create_demand(seller_id: int, product_id: int, qty: int) -> dict:
    """Create or update an open demand post."""
    if qty <= 0:
        return {"error": "qty must be positive"}
    from app.tools.inventory_tools import create_demand as _create_demand
    return _create_demand.invoke({"seller_id": seller_id, "product_id": product_id, "qty_needed": qty})


@mcp.tool()
def list_open_demands(seller_id: Optional[int] = None) -> list:
    """List open demand posts, optionally filtered by seller."""
    with session_scope() as session:
        stmt = (
            select(DemandPost, Seller, Product)
            .join(Seller, DemandPost.seller_id == Seller.seller_id)
            .join(Product, DemandPost.product_id == Product.product_id)
            .where(DemandPost.status == "open")
            .order_by(DemandPost.created_at.desc())
        )
        if seller_id:
            stmt = stmt.where(DemandPost.seller_id == seller_id)
        return [
            {
                "demand_id": d.demand_id, "seller_id": d.seller_id, "seller_name": s.name,
                "product_id": d.product_id, "product_name": p.name, "qty_needed": d.qty_needed,
            }
            for d, s, p in session.execute(stmt).all()
        ]


@mcp.tool()
def find_suppliers(product_id: int, qty_needed: int, exclude_seller_id: int = 0, target_price: float = 0.0) -> list:
    """Find ranked supplier options for a product."""
    return find_suppliers_tool.invoke({
        "product_id": product_id, "exclude_seller_id": exclude_seller_id,
        "qty_needed": qty_needed, "target_price": target_price,
    })


@mcp.tool()
def list_pending_transfers(seller_id: int, perspective: str = "incoming") -> list:
    """List pending/countered transfers. perspective: incoming | outgoing | countered."""
    if perspective not in {"incoming", "outgoing", "countered"}:
        return [{"error": "perspective must be incoming, outgoing, or countered"}]
    with session_scope() as session:
        return list_transfers(session, seller_id=seller_id, perspective=perspective)


@mcp.tool()
def get_transaction_history(seller_id: int, product_id: int, limit: int = 20) -> list:
    """Get recent transaction history for a seller-product pair."""
    import sqlite3
    from app.core.config import get_settings
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT txn_id, qty, agreed_price, status, negotiation_rounds, created_at "
        "FROM transactions WHERE seller_id=? AND product_id=? ORDER BY created_at DESC LIMIT ?",
        (seller_id, product_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@mcp.tool()
def run_analytics_query(sql: str) -> list:
    """Run a read-only SELECT query against the RetailFlow database."""
    try:
        validate_sql_query(sql)
    except ValueError as exc:
        return [{"error": str(exc)}]
    if not sql.lstrip().upper().startswith("SELECT"):
        return [{"error": "Only SELECT statements are allowed."}]
    with session_scope() as session:
        rows = session.execute(text(sql)).mappings().all()
        return [dict(r) for r in rows]


@mcp.tool()
def get_seller_profits(seller_id: int) -> list:
    """Get monthly profit history for a seller."""
    with session_scope() as session:
        return list_profit_history(session, seller_id)


@mcp.tool()
def predict_profit(seller_id: int) -> dict:
    """Predict next month's profit for a seller using ML."""
    return run_profit_prediction_agent(seller_id)


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 4) -> list:
    """Search the RAG knowledge base (pricing rules, market guidelines, seller catalogue)."""
    from app.rag.retriever import retrieve
    return retrieve(query, k=top_k)


@mcp.tool()
def list_sellers() -> list:
    """List all sellers on the network."""
    with session_scope() as session:
        rows = session.execute(select(Seller).order_by(Seller.seller_id)).scalars()
        return [{"seller_id": r.seller_id, "name": r.name, "location": r.location, "sector": r.sector} for r in rows]


@mcp.tool()
def list_products(category: Optional[str] = None) -> list:
    """List products, optionally filtered by category."""
    with session_scope() as session:
        stmt = select(Product).order_by(Product.category, Product.name)
        if category:
            stmt = stmt.where(Product.category == category)
        rows = session.execute(stmt).scalars()
        return [{"product_id": r.product_id, "name": r.name, "category": r.category, "unit": r.unit} for r in rows]


@mcp.tool()
def get_network_summary() -> dict:
    """High-level network metrics: sellers, products, open demands, pending transfers, monthly profit."""
    with session_scope() as session:
        month = datetime.now().strftime("%Y-%m")
        total_profit = session.execute(
            select(func.coalesce(func.sum(Profit.profit), 0)).where(Profit.month == month)
        ).scalar_one()
        return {
            "total_sellers":            session.query(Seller).count(),
            "total_products":           session.query(Product).count(),
            "open_demands":             session.query(DemandPost).filter(DemandPost.status == "open").count(),
            "pending_transfers":        session.query(Transfer).filter(Transfer.status.in_(["pending", "countered"])).count(),
            "network_profit_this_month": round(float(total_profit or 0.0), 2),
            "month":                    month,
        }


if __name__ == "__main__":
    import os
    # Use SSE transport in Docker/server deployments (set MCP_TRANSPORT=sse).
    # Falls back to stdio for local usage: uv run python mcp_server.py
    # Port is controlled via FASTMCP_PORT env var (default 8000).
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
