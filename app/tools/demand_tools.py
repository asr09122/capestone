"""Demand tools — sales stats for agents, and reorder quantity helper."""
import sqlite3
from datetime import datetime, timedelta

from langchain_core.tools import tool

from app.core.config import get_settings


def _conn():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def get_recent_sales(seller_id: int, product_id: int, days: int = 30) -> dict:
    """Get sales statistics for a seller-product pair over the last N days.

    Returns: total_qty, daily_avg, threshold (daily_avg × 7), transaction_count.
    Only counts completed transactions.
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS total_qty, COUNT(*) AS txn_count "
            "FROM transactions "
            "WHERE seller_id=? AND product_id=? AND status='completed' AND created_at>=?",
            (seller_id, product_id, cutoff),
        ).fetchone()

    total_qty = int(row["total_qty"])
    daily_avg = round(total_qty / days, 2)
    return {
        "total_qty": total_qty,
        "daily_avg": daily_avg,
        "threshold": round(daily_avg * 7, 2),
        "transaction_count": int(row["txn_count"]),
        "period_days": days,
    }


def predict_reorder_qty(seller_id: int, product_id: int, lead_time_days: int = 7) -> dict:
    """Moving-average reorder suggestion: daily_avg × lead_time_days, minimum 10 units."""
    stats = get_recent_sales.invoke({"seller_id": seller_id, "product_id": product_id, "days": 30})
    daily_avg = float(stats["daily_avg"])
    return {
        "suggested_qty": max(10, int(round(daily_avg * lead_time_days))),
        "daily_avg": round(daily_avg, 2),
    }
