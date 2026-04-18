# ── RetailFlow AI — FastAPI backend ───────────────────────────────────────────
# DB, FAISS index, and PDFs are committed to git and baked directly into the
# image — no persistent volume or seeding required.
FROM python:3.11-slim

WORKDIR /app

# System deps for faiss-cpu and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast package manager)
RUN pip install --no-cache-dir uv

# ── Dependency layer (cached unless pyproject.toml changes) ──────────────────
COPY pyproject.toml uv.lock* ./
RUN uv pip install --system --no-cache -r pyproject.toml 2>/dev/null || \
    uv pip install --system --no-cache \
        fastapi "uvicorn[standard]" langchain langchain-community \
        langchain-nvidia-ai-endpoints langchain-text-splitters langgraph \
        langgraph-checkpoint-sqlite \
        faiss-cpu sentence-transformers sqlalchemy alembic \
        "python-jose[cryptography]" pydantic-settings python-multipart \
        "passlib[bcrypt]" slowapi pandas numpy scikit-learn "mcp[cli]"

# ── Application source ────────────────────────────────────────────────────────
COPY app/        ./app/
COPY alembic/    ./alembic/
COPY alembic.ini ./
COPY scripts/    ./scripts/
COPY mcp_server.py ./

# ── Data (DB + FAISS index + PDFs committed to git, baked into image) ─────────
COPY data/       ./data/

# Make entrypoint executable
RUN chmod +x ./scripts/entrypoint.sh

EXPOSE 8000

# Health check used by Azure Container Apps readiness probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./scripts/entrypoint.sh"]
