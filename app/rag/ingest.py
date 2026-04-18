"""Ingest knowledge-base documents (PDF and TXT) into a FAISS vector store.

Covers the 'Unstructured Data' requirement:
  - .pdf files  → loaded with PyPDFLoader (page-by-page extraction)
  - .txt files  → loaded with TextLoader
Both are chunked, embedded with all-MiniLM-L6-v2, and stored in FAISS.
"""
import os
from pathlib import Path
from typing import List


def get_embeddings():
    """Return the HuggingFace embedding model (all-MiniLM-L6-v2)."""
    from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _load_documents(doc_dir: str) -> list:
    """Load all .txt files from doc_dir plus PDFs from doc_dir and project root."""
    from langchain_community.document_loaders import TextLoader, PyPDFLoader

    docs = []
    dir_path = Path(doc_dir)
    root_pdf_paths = sorted(
        path for path in dir_path.parent.glob("*.pdf") if path.is_file()
    )
    seen_paths: set[Path] = set()

    for path in sorted(dir_path.iterdir()) + root_pdf_paths:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if path.suffix.lower() == ".txt":
            try:
                loader = TextLoader(str(path), encoding="utf-8")
                docs.extend(loader.load())
                print(f"[ingest] Loaded TXT: {path.name}")
            except Exception as e:
                print(f"[ingest] Warning — could not load {path.name}: {e}")

        elif path.suffix.lower() == ".pdf":
            try:
                loader = PyPDFLoader(str(path))
                pages = loader.load()
                docs.extend(pages)
                print(f"[ingest] Loaded PDF: {path.name} ({len(pages)} pages)")
            except Exception as e:
                print(f"[ingest] Warning — could not load {path.name}: {e}")

    return docs


def ingest_documents(doc_dir: str, index_path: str) -> None:
    """Load documents, chunk them, embed, and save FAISS index.

    Supports both .txt and .pdf files in doc_dir.
    """
    from langchain_community.vectorstores import FAISS
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    if not os.path.isdir(doc_dir):
        raise FileNotFoundError(f"Knowledge-base directory not found: {doc_dir}")

    docs = _load_documents(doc_dir)
    if not docs:
        raise ValueError(f"No .txt or .pdf files found in {doc_dir}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=60,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"[ingest] {len(docs)} docs -> {len(chunks)} chunks")

    embeddings = get_embeddings()
    vectorstore = FAISS.from_documents(chunks, embeddings)

    os.makedirs(index_path, exist_ok=True)
    vectorstore.save_local(index_path)
    print(f"[ingest] FAISS index saved to {index_path}")


if __name__ == "__main__":
    from app.core.config import get_settings
    s = get_settings()
    ingest_documents(s.pdf_dir, s.faiss_index_path)
