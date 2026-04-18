"""Demand Agent — stock health check and reorder recommendation."""
from langchain.agents import create_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from app.core.config import get_settings
from app.tools.demand_tools import get_recent_sales, predict_reorder_qty


PROMPT = """You are RetailFlow's Demand Agent — a stock advisor for retail store owners.

TOOL: get_recent_sales(seller_id, product_id, days) — returns total_qty, daily_avg,
threshold (daily_avg × 7), transaction_count. Call this first.

INTERPRET THE DATA:
- stock < threshold → LOW — reorder urgently.
- threshold ≤ stock < threshold × 2 → MODERATE — monitor.
- stock ≥ threshold × 2 → HEALTHY — no action needed.
- daily_avg = 0 → slow-moving product, flag it.

RESPOND WITH:
1. Stock status: LOW / MODERATE / HEALTHY.
2. The threshold number so the owner understands the benchmark.
3. Recommended reorder quantity (given by the ML helper in the message).
4. One practical reason — e.g. "At this pace you will run out in 4 days."
Under 100 words. Use ₹ for prices. Read-only — never modify data."""


def run_demand_agent(seller_id: int, product_id: int, current_stock: int) -> dict:
    stats = get_recent_sales.invoke({"seller_id": seller_id, "product_id": product_id, "days": 30})
    reorder = predict_reorder_qty(seller_id, product_id)
    should_reorder = current_stock < float(stats["threshold"])

    fallback = (
        f"Stock: {current_stock} units. Threshold: {stats['threshold']}. "
        f"{'Reorder now.' if should_reorder else 'Stock is healthy.'} "
        f"Suggested qty: {reorder['suggested_qty']}."
    )

    settings = get_settings()
    if not settings.nvidia_api_key:
        return {"threshold": stats["threshold"], "should_reorder": should_reorder,
                "suggested_qty": reorder["suggested_qty"], "explanation": fallback}

    agent = create_agent(
        model=ChatNVIDIA(model=settings.llm_model, api_key=settings.nvidia_api_key,
                         temperature=0.0, max_tokens=700),
        tools=[get_recent_sales],
        system_prompt=PROMPT,
    )

    result = agent.invoke({"messages": [{"role": "user", "content": (
        f"Seller {seller_id}, product {product_id}, current stock {current_stock} units. "
        f"ML suggests reordering {reorder['suggested_qty']} units. Analyse and explain."
    )}]})

    explanation = fallback
    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str) or not content.strip():
            continue
        if "<tool_call>" in content or "<function=" in content:
            continue
        explanation = content
        break

    return {"threshold": stats["threshold"], "should_reorder": should_reorder,
            "suggested_qty": reorder["suggested_qty"], "explanation": explanation}
