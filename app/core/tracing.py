from langsmith import traceable, Client
from app.core.config import get_settings


def init_tracing():
    """Enable LangSmith tracing if API key is configured."""
    settings = get_settings()
    if settings.langsmith_api_key and settings.langsmith_tracing:
        import os

        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        return True
    return False


@traceable
def trace_agent(name: str):
    """Decorator for tracing agent functions."""
    pass


def start_traced_run(name: str, inputs: dict):
    """Start a traced run manually."""
    settings = get_settings()
    if not settings.langsmith_api_key or not settings.langsmith_tracing:
        return None
    client = Client()
    return client.create_run(inputs=inputs, name=name, run_type="agent")
