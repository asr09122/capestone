from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.ml_agent import run_profit_prediction_agent
from app.core.security import ensure_actor_can_access_seller, get_current_user

router = APIRouter()

@router.get("/predict-profit/{seller_id}")
async def get_profit_prediction(
    seller_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Predict the next month's profit for a specific seller using ML."""
    ensure_actor_can_access_seller(current_user, seller_id)
    prediction = run_profit_prediction_agent(seller_id)
    if "error" in prediction:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=prediction["error"])
    return prediction
