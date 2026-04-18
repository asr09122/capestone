"""Transfer routes for supplier approval and counter-offers."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from app.core.security import get_current_user, require_seller
from app.db.database import session_scope
from app.db.models import Transfer
from app.services.workflow_service import (
    MAX_NEGOTIATION_ROUNDS,
    accept_counter as accept_counter_service,
    approve_transfer,
    counter_transfer,
    list_transfers,
    reject_transfer as reject_transfer_service,
    serialize_transfer,
)

router = APIRouter()


class TransferResponse(BaseModel):
    approved: bool
    reason: Optional[str] = None


class NegotiateRequest(BaseModel):
    counter_price: float

    @field_validator("counter_price")
    @classmethod
    def validate_counter_price(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("counter_price must be positive")
        return value


@router.get("/pending-transfers")
async def get_pending_transfers(current_user: dict = Depends(require_seller)):
    with session_scope() as session:
        return list_transfers(
            session,
            seller_id=current_user["seller_id"],
            perspective="incoming",
        )


@router.get("/my-outgoing-requests")
async def get_my_outgoing_requests(current_user: dict = Depends(require_seller)):
    with session_scope() as session:
        return list_transfers(
            session,
            seller_id=current_user["seller_id"],
            perspective="outgoing",
        )


@router.get("/countered-transfers")
async def get_countered_transfers(current_user: dict = Depends(require_seller)):
    with session_scope() as session:
        return list_transfers(
            session,
            seller_id=current_user["seller_id"],
            perspective="countered",
        )


@router.post("/respond-transfer/{transfer_id}")
async def respond_to_transfer(
    transfer_id: int,
    req: TransferResponse,
    current_user: dict = Depends(require_seller),
):
    with session_scope() as session:
        transfer = session.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
        if transfer.from_seller_id != current_user["seller_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the supplier can approve or reject this transfer.",
            )
        try:
            if req.approved:
                result = approve_transfer(session, transfer_id)
                return {
                    **result,
                    "message": f"Transfer #{transfer_id} approved and executed.",
                }
            result = reject_transfer_service(session, transfer_id)
            return {
                **result,
                "message": f"Transfer #{transfer_id} rejected.",
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/negotiate-transfer/{transfer_id}")
async def negotiate_transfer(
    transfer_id: int,
    req: NegotiateRequest,
    current_user: dict = Depends(require_seller),
):
    with session_scope() as session:
        transfer = session.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
        if transfer.from_seller_id != current_user["seller_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the supplier can send a counter-offer.",
            )
        try:
            result = counter_transfer(session, transfer_id, req.counter_price)
            return {
                **result,
                "max_negotiation_rounds": MAX_NEGOTIATION_ROUNDS,
                "message": f"Counter-offer of Rs. {req.counter_price:.2f}/unit sent to buyer.",
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/accept-counter/{transfer_id}")
async def accept_counter(
    transfer_id: int,
    current_user: dict = Depends(require_seller),
):
    with session_scope() as session:
        transfer = session.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
        if transfer.to_seller_id != current_user["seller_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the buyer can accept this counter-offer.",
            )
        try:
            result = accept_counter_service(session, transfer_id)
            return {
                **result,
                "message": (
                    f"Counter accepted at Rs. {result['transfer_price']:.2f}/unit. "
                    "Supplier still needs to approve shipment."
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/buyer-counter/{transfer_id}")
async def buyer_counter(
    transfer_id: int,
    req: NegotiateRequest,
    current_user: dict = Depends(require_seller),
):
    with session_scope() as session:
        transfer = session.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
        if transfer.to_seller_id != current_user["seller_id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Only the buyer can counter this offer.")
        try:
            # accept the counter at the supplier price, then set buyer's counter price
            accept_counter_service(session, transfer_id)
            # overwrite transfer_price with buyer's counter and re-serialize
            transfer = session.get(Transfer, transfer_id)
            transfer.transfer_price = req.counter_price
            session.flush()
            result = serialize_transfer(transfer, session)
            return {**result, "message": f"Your counter of Rs. {req.counter_price:.2f}/unit sent. Waiting for supplier."}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/reject-counter/{transfer_id}")
async def reject_counter(
    transfer_id: int,
    current_user: dict = Depends(require_seller),
):
    with session_scope() as session:
        transfer = session.get(Transfer, transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfer not found")
        if transfer.to_seller_id != current_user["seller_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the buyer can reject this counter-offer.",
            )
        try:
            result = reject_transfer_service(session, transfer_id, close_demand=True)
            return {
                **result,
                "message": "Counter rejected. Transfer closed.",
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
