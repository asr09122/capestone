"""RAG tools — document retrieval and transaction history for agent reasoning."""
import sqlite3

from langchain_core.tools import tool

from app.core.config import get_settings


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def retrieve_docs(query: str) -> list:
    """Retrieve relevant knowledge-base chunks for a given query.

    Searches pricing_rules, market_guidelines, and seller_catalogue.
    Returns a list of relevant text passages (up to 4).
    """
    from app.rag.retriever import retrieve
    return retrieve(query, k=4)


@tool
def get_transaction_history(seller_id: int, product_id: int, limit: int = 20) -> list:
    """Get recent transaction history for a seller-product pair.

    Returns a list of dicts with: txn_id, qty, agreed_price, status,
    negotiation_rounds, created_at.
    Ordered by most recent first.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT txn_id, qty, agreed_price, status, negotiation_rounds, created_at
            FROM transactions
            WHERE seller_id = ? AND product_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (seller_id, product_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_avg_transaction_price(seller_id: int, product_id: int, days: int = 30) -> float:
    """Get average agreed price for completed transactions in the last N days.
    Used for anomaly detection (non-tool, called directly by billing workflow).
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(agreed_price) AS avg_price FROM transactions "
            "WHERE seller_id = ? AND product_id = ? "
            "AND status = 'completed' AND created_at >= ?",
            (seller_id, product_id, cutoff),
        ).fetchone()
    return float(row["avg_price"]) if row["avg_price"] else 0.0
