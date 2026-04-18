"""Seller Match Agent — ranks suppliers and explains the best pick."""

from langchain.agents import create_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langsmith import traceable

from app.core.config import get_settings
from app.tools.transfer_tools import find_sellers_with_stock


PROMPT = """You are RetailFlow's Seller Match Agent — a procurement advisor for retail store owners.

TOOL: find_sellers_with_stock(product_id, qty_needed, exclude_seller_id, target_price)
Returns candidates with: seller_name, location, stock_qty, selling_price,
fulfillable_qty, full_cover (bool), price_delta (their price minus buyer's target).

RANK SUPPLIERS BY:
1. Full coverage first — can they supply the entire order alone?
2. Price closeness — whose price is nearest to the buyer's target?
3. Location — same city as buyer is a tiebreaker.
4. If no single supplier covers the order, suggest the top 2 as a split plan.

RESPOND WITH:
- "Best match: [seller_name] at ₹[price] for up to [qty] units."
- If split plan: "Split: [seller1] qty×₹[price] + [seller2] qty×₹[price]"
- One sentence why this is the best pick.
- Under 100 words. Use ₹ for prices."""


@traceable(name="seller_agent")
def run_seller_agent(
    requesting_seller_id: int, product_id: int, qty_needed: int, target_price: float
) -> dict:
    candidates = find_sellers_with_stock.invoke(
        {
            "product_id": product_id,
            "qty_needed": qty_needed,
            "exclude_seller_id": requesting_seller_id,
            "target_price": float(target_price),
        }
    )

    best = candidates[0] if candidates else None
    fallback = (
        "No suppliers have stock for this product."
        if not best
        else f"Best: {best['seller_name']} at ₹{best['selling_price']:.2f}, up to {best['fulfillable_qty']} units."
    )

    settings = get_settings()
    if not settings.nvidia_api_key:
        return {
            "candidates": candidates,
            "suggested_seller_id": best["seller_id"] if best else None,
            "explanation": fallback,
        }

    agent = create_agent(
        model=ChatNVIDIA(
            model=settings.llm_model,
            api_key=settings.nvidia_api_key,
            temperature=0.0,
            max_tokens=700,
        ),
        tools=[find_sellers_with_stock],
        system_prompt=PROMPT,
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Buyer seller_id={requesting_seller_id} needs {qty_needed} units of product_id={product_id} "
                        f"at target ₹{target_price:.2f}/unit. Find and rank suppliers."
                    ),
                }
            ]
        }
    )

    explanation = fallback
    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str) or not content.strip():
            continue
        if "<tool_call>" in content or "<function=" in content:
            continue
        explanation = content
        break

    return {
        "candidates": candidates,
        "suggested_seller_id": best["seller_id"] if best else None,
        "explanation": explanation,
    }
