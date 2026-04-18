"""Ask route — natural language query router across agents."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.agents.graph import route_query_to_agent
from app.core.security import ensure_actor_can_access_seller, get_current_user

router = APIRouter()


class AskRequest(BaseModel):
    query: str
    seller_id: int
    product_id: Optional[int] = None


@router.post("/ask")
async def ask(
    req: AskRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Route a natural-language question to the appropriate agent.

    Routing logic:
    - "why / how / explain / reason / anomaly" → RAG Agent
    - "profit / revenue / cost / analytics"    → SQL Agent
    - everything else (stock / demand / threshold) → Demand Agent
    """
    if not req.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query cannot be empty",
        )

    route = route_query_to_agent(req.query)

    try:
        ensure_actor_can_access_seller(current_user, req.seller_id)
        if route == "rag":
            from app.agents.rag_agent import run_rag_agent
            answer = run_rag_agent(req.query, req.seller_id, req.product_id)

        elif route == "sql":
            from app.agents.sql_agent import run_sql_agent
            answer = run_sql_agent(req.query)

        elif route == "ml":
            from app.agents.ml_agent import run_profit_prediction_agent
            result = run_profit_prediction_agent(req.seller_id)
            answer = result.get("explanation", "Profit forecast generated.")

        elif route == "seller":
            if req.product_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="product_id is required for supplier matching queries",
                )
            from app.agents.seller_agent import run_seller_agent
            seller_result = run_seller_agent(
                requesting_seller_id=req.seller_id,
                product_id=req.product_id,
                qty_needed=20,
                target_price=0.0,
            )
            answer = seller_result.get("explanation", "Supplier analysis complete.")

        else:  # demand / stock
            if req.product_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="product_id is required for stock/demand queries",
                )
            from app.tools.inventory_tools import get_inventory_raw
            from app.agents.demand_agent import run_demand_agent

            inv = get_inventory_raw(req.seller_id, req.product_id)
            current_stock = inv["stock_qty"] if inv else 0
            result = run_demand_agent(req.seller_id, req.product_id, current_stock)
            answer = result.get("explanation", "Demand analysis complete.")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent error: {e}",
        )

    return {
        "query": req.query,
        "agent_used": route,
        "answer": answer,
    }
