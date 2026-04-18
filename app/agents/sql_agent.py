"""SQL Agent — natural language to read-only SQL analytics."""

from sqlalchemy import text

from langchain.agents import create_agent
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langsmith import traceable

from app.core.config import get_settings
from app.db.database import session_scope
from app.guardrails.validators import validate_sql_query


@traceable(name="sql_agent")
def run_sql_agent(query: str) -> str:
    try:
        validate_sql_query(query)
    except ValueError as exc:
        return f"Query blocked: {exc}"

    settings = get_settings()

    if not settings.nvidia_api_key:
        if query.lstrip().upper().startswith("SELECT"):
            with session_scope() as session:
                rows = session.execute(text(query)).mappings().all()
                return str([dict(r) for r in rows[:10]]) if rows else "No rows found."
        return "SQL agent unavailable — add NVIDIA_API_KEY to .env."

    llm = ChatNVIDIA(
        model=settings.llm_model,
        api_key=settings.nvidia_api_key,
        temperature=0.0,
        max_tokens=1024,
    )

    db = SQLDatabase.from_uri(
        settings.database_url,
        include_tables=[
            "products",
            "sellers",
            "inventory",
            "demand_posts",
            "transactions",
            "transfers",
            "profits",
            "users",
        ],
    )

    prompt = """You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {dialect} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {top_k} results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

You MUST double check your query before executing it. If you get an error while
executing a query, rewrite the query and try again.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the database.

To start you should ALWAYS look at the tables in the database to see what you
can query. Do NOT skip this step. Then you should query the schema of the most
relevant tables.

Additional context — this is a kirana store B2B supply network:
- Always JOIN sellers and products tables to show names instead of raw IDs.
- Use ₹ with 2 decimal places for all money values in your explanation.
- profits.month is stored as 'YYYY-MM' — filter by it when the user mentions a time period.""".format(
        dialect=db.dialect, top_k=5
    )

    agent = create_agent(
        model=llm,
        tools=SQLDatabaseToolkit(db=db, llm=llm).get_tools(),
        system_prompt=prompt,
    )

    result = agent.invoke({"messages": [{"role": "user", "content": query}]})

    for msg in reversed(result.get("messages", [])):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str) or not content.strip():
            continue
        if "<tool_call>" in content or "<function=" in content:
            continue
        return content

    return "No result generated."
