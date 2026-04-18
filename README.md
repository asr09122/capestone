# RetailFlow AI

**B2B Smart Supply, Billing & Demand Intelligence System**

Event-driven GenAI system for retail stores using LangChain, LangGraph, FastAPI, ChatNVIDIA, SQLite, and FAISS.

---

## Quick Start

### 1. Install dependencies
```bash
uv sync
```

### 2. Configure environment
Edit `.env` and set your `NVIDIA_API_KEY`.

### 3. Initialize database
```bash
# Option A — Alembic migrations (recommended for production)
uv run alembic upgrade head
uv run python scripts/seed_db.py

# Option B — direct init (dev only)
uv run python scripts/init_db.py
uv run python scripts/seed_db.py
```

### 4. Build RAG index (downloads ~90MB model on first run)
```bash
uv run python scripts/init_rag.py
```

### 5. Start server
```bash
# Development
uv run uvicorn app.main:app --reload

# Production
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Environment variables
| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | — | Required for LLM |
| `SECRET_KEY` | fallback-secret-key | **Change in production** |
| `ALLOWED_ORIGINS` | http://localhost:8501 | Comma-separated CORS origins |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | JWT expiry |

API docs: http://localhost:8000/docs

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/token` | Get JWT token |
| POST | `/billing` | Process a sale → triggers workflow |
| POST | `/billing/approve/{thread_id}` | Approve/reject transfer |
| POST | `/demand` | Manual demand post |
| POST | `/demand/approve/{thread_id}` | Approve/reject demand transfer |
| POST | `/ask` | Natural language query (RAG/SQL/Demand) |
| GET  | `/sql` | SQL analytics query |
| GET  | `/health` | Health check |

---

## Workflow

```
POST /billing
     │
     ▼
billing_node ──→ threshold_check_node
                        │
               stock >= threshold? ──→ END
                        │
                   demand_node
                        │
               seller_matching_node
                        │
               human_approval_node  ← INTERRUPT (awaiting /approve)
                        │
              approved? ──→ transfer_node ──→ END
                        │
                  rejection_node ──→ END
```

---

## Test Credentials

| Username | Password | Seller ID |
|----------|----------|-----------|
| admin | retailflow123 | 1 |
| seller1 | password1 | 1 |

---

## Architecture

```
app/
├── main.py              FastAPI entry point
├── routes/              API layer
│   ├── auth.py          JWT authentication
│   ├── billing.py       Billing + approval
│   ├── demand.py        Manual demand + approval
│   ├── ask.py           Query routing (RAG/SQL/Demand)
│   └── sql.py           SQL analytics
├── agents/              LangGraph agents
│   ├── graph.py         State machine (workflow)
│   ├── rag_agent.py     Explainability (RAG)
│   ├── demand_agent.py  Threshold + demand creation
│   ├── seller_agent.py  A2A seller matching
│   └── sql_agent.py     Analytics (SQLDatabaseToolkit)
├── tools/               Tool layer (DB access)
│   ├── inventory_tools.py
│   ├── demand_tools.py
│   ├── transfer_tools.py
│   └── rag_tools.py
├── rag/
│   ├── ingest.py        FAISS index builder
│   └── retriever.py     Similarity search
├── core/
│   ├── config.py        Pydantic settings
│   └── security.py      JWT auth
├── guardrails/
│   └── validators.py    Input + SQL validation
└── memory/
    └── chat_memory.py   Graph checkpointer
```
