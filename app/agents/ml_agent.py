"""ML Agent — profit prediction using linear regression + moving average."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from langchain.agents import create_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langsmith import traceable

from app.core.config import get_settings
from app.db.database import session_scope
from app.services.workflow_service import list_profit_history

# predict_reorder_qty lives in demand_tools — it's a demand/sales concept, not ML
from app.tools.demand_tools import predict_reorder_qty  # noqa: F401 — re-exported for graph.py


PROMPT = """You are RetailFlow's Profit Prediction Agent — a financial advisor for retail store owners.

You will receive a dict with:
- historical_months_used: months of data the model used
- predicted_next_month_profit_lr: linear regression prediction (long-term trend)
- predicted_next_month_profit_ma: 3-month moving average prediction (recent trend)

INTERPRET:
- LR > MA → business on upward long-term trajectory.
- LR < MA → recent months outperforming the trend.
- Both agree (within 10%) → reliable forecast.
- They diverge significantly → flag uncertainty.

RESPOND WITH:
1. Both forecast numbers in ₹.
2. One sentence on trend direction: growing / flat / declining.
3. One practical suggestion:
   - Growing → "Consider expanding your top-selling product range."
   - Flat → "Focus on reducing procurement costs to improve margins."
   - Declining → "Review your pricing — you may be selling below market rate."
4. If historical_months_used < 6, add: "Forecast confidence is low with only N months of data."
Under 120 words. Use ₹. No technical jargon."""


@traceable(name="ml_agent")
def run_profit_prediction_agent(seller_id: int) -> dict:
    """Run ML prediction and ask the LLM to explain the forecast in plain language."""
    with session_scope() as session:
        history = list_profit_history(session, seller_id)

    if len(history) < 3:
        msg = "Need at least 3 months of data to predict."
        return {"seller_id": seller_id, "error": msg, "explanation": msg}

    df = pd.DataFrame(history)
    df["t"] = np.arange(len(df))
    lr = round(
        float(LinearRegression().fit(df[["t"]], df["profit"]).predict([[len(df)]])[0]),
        2,
    )
    ma = round(float(df["profit"].tail(3).mean()), 2)

    prediction = {
        "seller_id": seller_id,
        "historical_months_used": len(df),
        "predicted_next_month_profit_lr": lr,
        "predicted_next_month_profit_ma": ma,
    }
    fallback = (
        f"Next month: ₹{lr:.2f} (linear regression), ₹{ma:.2f} (3-month average)."
    )

    settings = get_settings()
    if not settings.nvidia_api_key:
        prediction["explanation"] = fallback
        return prediction

    agent = create_agent(
        model=ChatNVIDIA(
            model=settings.llm_model,
            api_key=settings.nvidia_api_key,
            temperature=0.0,
            max_tokens=500,
        ),
        tools=[],
        system_prompt=PROMPT,
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Explain forecast for seller {seller_id}: {prediction}",
                }
            ]
        }
    )

    prediction["explanation"] = fallback
    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str) or not content.strip():
            continue
        if "<tool_call>" in content or "<function=" in content:
            continue
        prediction["explanation"] = content
        break

    return prediction
