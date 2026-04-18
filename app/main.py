"""RetailFlow AI — FastAPI application entry point (production-ready)."""

import logging
import os
import time

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.routes import auth, billing, demand, ask, sql, admin, ml, transfer
from app.core.tracing import init_tracing

# ── LangSmith tracing ──────────────────────────────────────────────────────────────
init_tracing()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("retailflow")

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RetailFlow AI",
    description=(
        "B2B Smart Supply, Billing & Demand Intelligence System. "
        "Event-driven AI with multi-agent orchestration for retail stores."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Request logging middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error. Please try again later."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(billing.router, tags=["Billing"])
app.include_router(demand.router, tags=["Demand"])
app.include_router(ask.router, tags=["Ask Agent"])
app.include_router(sql.router, tags=["SQL Analytics"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(ml.router, prefix="/ml", tags=["ML Agent"])
app.include_router(transfer.router, tags=["Transfers"])


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    from app.core.config import get_settings
    from app.core.security import bootstrap_role_compatibility

    settings = get_settings()
    bootstrap_role_compatibility()
    if not os.path.isfile(settings.db_path):
        logger.warning(
            "DB not found at '%s'. Ensure you have run Alembic migrations: `alembic upgrade head` and seeded data.",
            settings.db_path,
        )
    if not os.path.isdir(settings.faiss_index_path):
        logger.warning(
            "FAISS index not found at '%s'. Run: uv run python scripts/init_rag.py",
            settings.faiss_index_path,
        )
    logger.info("RetailFlow AI started — docs at /docs")


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "status": "ok",
        "db_exists": os.path.isfile(settings.db_path),
        "faiss_index_exists": os.path.isdir(settings.faiss_index_path),
    }


@app.get("/", tags=["Root"])
async def root():
    return {"project": "RetailFlow AI", "version": "1.0.0", "docs": "/docs"}
