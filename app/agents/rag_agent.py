"""RAG Agent — explains pricing anomalies and business decisions."""

from langchain.agents import create_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import AIMessage, ToolMessage
from langsmith import traceable

from app.core.config import get_settings
from app.tools.rag_tools import retrieve_docs, get_transaction_history


PROMPT = """You are RetailFlow's Explainability Agent — a plain-language advisor for retail store owners.

TOOLS:
- retrieve_docs: searches pricing rules, market guidelines, and seller catalogue. Call this first.
- get_transaction_history: fetches recent transactions for a seller-product pair. Call this when
  a specific seller and product are mentioned, to reference actual prices instead of generalities.

HOW TO ANSWER:
1. Cite the business rule or guideline that applies.
2. Reference the actual data — recent prices, the anomaly threshold crossed, stock levels.
3. End with one clear action the owner should take.
4. Under 150 words. Use ₹ for prices. No jargon.
5. If no relevant rule exists in the knowledge base, say so honestly.
6. NEVER include citation markers like 【retrieve_docs†0】 or source references in your reply — just state the facts directly.

SCENARIOS YOU WILL HANDLE:
- Price anomaly: billed price deviates >20% from the 30-day average.
- Low stock: stock dropped below 7 × daily average sales.
- Supplier suggestion: why a particular seller was ranked first.
- Transfer rejection or counter-offer explanation.
- Why a demand post was auto-created after billing."""


def _extract_final_text(messages: list) -> str:
    """Return the last AIMessage that contains plain text — skip tool calls and tool results."""
    for msg in reversed(messages):
        # Skip ToolMessage (tool results fed back to the model)
        if isinstance(msg, ToolMessage):
            continue
        # Get content
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        # Skip raw tool call XML that the model emitted but didn't finish processing
        if "<tool_call>" in text or "<function=" in text or text.startswith('{"tool'):
            continue
        # Skip messages that are just tool call JSON blobs
        if text.startswith("<") and ">" in text:
            continue
        # Strip citation markers e.g. 【retrieve_docs†0】
        import re

        text = re.sub(r"【[^】]*】", "", text).strip()
        if not text:
            continue
        return text
    return ""


@traceable(name="rag_agent")
def run_rag_agent(query: str, seller_id: int, product_id: int | None = None) -> str:
    settings = get_settings()

    # Fallback when no API key — just return the first doc chunk
    if not settings.nvidia_api_key:
        docs = retrieve_docs.invoke({"query": query})
        return docs[0][:300] if docs else "No context available."

    # Pre-fetch context so we always have a fallback even if the agent misbehaves
    docs = retrieve_docs.invoke({"query": query})
    fallback = (
        docs[0][:300] if docs else "No supporting context found in knowledge base."
    )

    agent = create_agent(
        model=ChatNVIDIA(
            model=settings.llm_model,
            api_key=settings.nvidia_api_key,
            temperature=0.0,
            max_tokens=900,
        ),
        tools=[retrieve_docs, get_transaction_history],
        system_prompt=PROMPT,
    )

    message = query
    if seller_id:
        message += f" | Seller ID: {seller_id}"
    if product_id:
        message += f" | Product ID: {product_id}"

    try:
        result = agent.invoke({"messages": [{"role": "user", "content": message}]})
        answer = _extract_final_text(result.get("messages", []))
        return answer if answer else fallback
    except Exception:
        return fallback
