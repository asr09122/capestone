"""Manual demand routes — HITL at every step (same state machine as billing).

Flow:
  POST /demand                       → start workflow, interrupt at ask_price
  POST /demand/{tid}/set-price       → resume with user's qty + target price
  POST /demand/{tid}/choose-seller   → resume with chosen supplier + offer price
  POST /demand/{tid}/cancel          → abandon workflow
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from langgraph.types import Command

from app.agents.graph import get_graph, KiranaState
from app.core.security import ensure_actor_can_access_seller, get_current_user
from app.guardrails.validators import validate_demand_input

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class DemandRequest(BaseModel):
    seller_id: int
    product_id: int
    quantity: int

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v


class SetPriceRequest(BaseModel):
    qty: int
    target_price: float

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("qty must be positive")
        return v

    @field_validator("target_price")
    @classmethod
    def price_positive(cls, v):
        if v <= 0:
            raise ValueError("target_price must be positive")
        return v


class ChooseSellerRequest(BaseModel):
    seller_id: int
    offer_price: float
    qty: Optional[int] = None
    use_split: bool = False

    @field_validator("offer_price")
    @classmethod
    def price_positive(cls, v):
        if v <= 0:
            raise ValueError("offer_price must be positive")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────

def _initial_state(seller_id: int, product_id: int, quantity: int) -> KiranaState:
    return {
        "seller_id": seller_id,
        "product_id": product_id,
        "quantity": quantity,
        "price": 0.0,
        "trigger": "demand",
        "stock": None, "threshold": None, "daily_avg": None,
        "suggested_qty": quantity, "market_avg_price": None,
        "user_qty_needed": None, "user_target_price": None,
        "demand_id": None, "demand_created": False,
        "candidates": None, "split_plan": None, "split_confirmed": None,
        "chosen_seller_id": None, "chosen_price": None,
        "transfer_id": None, "transfer_ids": None, "transfer_qty": None, "transfer_suggested": False,
        "anomaly_detected": False, "anomaly_explanation": None,
        "next_step": None, "result": None, "error": None,
    }


def _shape_response(thread_id: str, graph, config) -> dict:
    snapshot = graph.get_state(config)
    values = dict(snapshot.values)

    pending_prompt = None
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if interrupts:
        first = interrupts[0]
        pending_prompt = getattr(first, "value", None) or first

    paused = bool(snapshot.next)
    step = (pending_prompt or {}).get("step") if isinstance(pending_prompt, dict) else None
    if not paused:
        step = "done"

    return {
        "thread_id": thread_id,
        "trigger": values.get("trigger"),
        "seller_id": values.get("seller_id"),
        "product_id": values.get("product_id"),
        "paused": paused,
        "next_step": step,
        "prompt": pending_prompt if paused else None,
        "demand_id": values.get("demand_id"),
        "demand_created": values.get("demand_created", False),
        "transfer_id": values.get("transfer_id"),
        "transfer_ids": values.get("transfer_ids"),
        "transfer_qty": values.get("transfer_qty"),
        "chosen_seller_id": values.get("chosen_seller_id"),
        "chosen_price": values.get("chosen_price"),
        "split_plan": values.get("split_plan"),
        "split_confirmed": values.get("split_confirmed"),
        "result": values.get("result"),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/demand")
async def create_manual_demand(
    req: DemandRequest,
    current_user: dict = Depends(get_current_user),
):
    """Start a manual demand workflow — pauses at ask_price for user confirmation."""
    try:
        ensure_actor_can_access_seller(current_user, req.seller_id)
        validate_demand_input(req.seller_id, req.product_id, req.quantity)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except HTTPException:
        raise

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    graph = get_graph()
    try:
        graph.invoke(
            _initial_state(req.seller_id, req.product_id, req.quantity),
            config=config,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return _shape_response(thread_id, graph, config)


@router.post("/demand/{thread_id}/set-price")
async def demand_set_price(
    thread_id: str,
    req: SetPriceRequest,
    current_user: dict = Depends(get_current_user),
):
    config = {"configurable": {"thread_id": thread_id}}
    graph = get_graph()
    snap = graph.get_state(config)
    if not snap.next:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No paused workflow found for thread_id={thread_id}",
        )
    try:
        graph.invoke(
            Command(resume={"qty": req.qty, "target_price": req.target_price}),
            config=config,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    return _shape_response(thread_id, graph, config)


@router.post("/demand/{thread_id}/choose-seller")
async def demand_choose_seller(
    thread_id: str,
    req: ChooseSellerRequest,
    current_user: dict = Depends(get_current_user),
):
    config = {"configurable": {"thread_id": thread_id}}
    graph = get_graph()
    snap = graph.get_state(config)
    if not snap.next:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No paused workflow found for thread_id={thread_id}",
        )
    try:
        graph.invoke(
            Command(resume={
                "seller_id": req.seller_id,
                "offer_price": req.offer_price,
                "qty": req.qty,
                "use_split": req.use_split,
            }),
            config=config,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    return _shape_response(thread_id, graph, config)


@router.post("/demand/{thread_id}/cancel")
async def demand_cancel(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
):
    return {"thread_id": thread_id, "cancelled": True, "result": "Workflow cancelled by user."}
