"""SQL analytics route — SELECT-only query endpoint."""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agents.sql_agent import run_sql_agent
from app.core.security import get_current_user
from app.guardrails.validators import validate_sql_query

router = APIRouter()


@router.get("/sql")
async def sql_analytics(
    query: str = Query(..., description="Natural language or SQL SELECT query"),
    current_user: dict = Depends(get_current_user),
):
    """
    Run an analytics query via the SQL Agent.

    Accepts natural language (e.g. "show top 5 sellers by profit last month")
    or direct SQL SELECT statements.

    Only SELECT queries are permitted — all modification operations are blocked.
    """
    if not query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query cannot be empty",
        )

    # Pre-flight guardrail for raw SQL
    try:
        validate_sql_query(query)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    try:
        result = run_sql_agent(query)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL agent error: {e}",
        )

    return {"query": query, "result": result}
