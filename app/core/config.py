from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    nvidia_api_key: str = ""
    # All ReAct agents (RAG, Demand, Seller, SQL) share this LLM via ChatNVIDIA.
    llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    secret_key: str = "fallback-secret-key"
    database_url: str = "sqlite:///data/retailflow.db"
    db_path: str = "data/retailflow.db"
    faiss_index_path: str = "data/faiss_index"
    pdf_dir: str = "data/pdfs"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # LangSmith tracing
    langsmith_api_key: str = ""
    langchain_api_key: str = ""
    langsmith_project: str = "retailflow-ai"
    langsmith_tracing: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
