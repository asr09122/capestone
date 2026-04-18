"""Build the FAISS vector index from knowledge-base text files."""
import os
import sys

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.rag.ingest import ingest_documents


def main():
    settings = get_settings()
    print(f"PDF source  : {settings.pdf_dir}")
    print(f"Index target: {settings.faiss_index_path}")
    ingest_documents(settings.pdf_dir, settings.faiss_index_path)
    print("RAG initialisation complete.")


if __name__ == "__main__":
    main()
