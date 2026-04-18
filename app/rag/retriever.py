"""FAISS retriever — singleton vectorstore with lazy load."""
import os
from typing import Optional

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from app.core.config import get_settings

_vectorstore: Optional[FAISS] = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_vectorstore() -> FAISS:
    global _vectorstore
    if _vectorstore is None:
        settings = get_settings()
        index_path = settings.faiss_index_path
        if not os.path.isdir(index_path):
            raise RuntimeError(
                f"FAISS index not found at '{index_path}'. "
                "Run: python scripts/init_rag.py"
            )
        embeddings = _get_embeddings()
        _vectorstore = FAISS.load_local(
            index_path,
            embeddings,
            allow_dangerous_deserialization=True,
        )
    return _vectorstore


def retrieve(query: str, k: int = 4) -> list[str]:
    """Return top-k relevant text chunks for the query."""
    vs = get_vectorstore()
    docs = vs.similarity_search(query, k=k)
    return [doc.page_content for doc in docs]
