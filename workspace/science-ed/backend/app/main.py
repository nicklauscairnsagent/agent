"""
ScienceEd Backend — FastAPI Application

A self-hosted tracking, AI-feedback, and teacher-dashboard backend
for the Nicklaus Cairns interactive science simulation platform.

Observability:
    - Structured JSON logging via LoggingMiddleware (method, path, status, duration)
    - Sentry error tracking (when SENTRY_DSN configured)
    - Startup self-check: DB connectivity, model count, startup time
    - Health endpoints at /health and /api/v1/health
"""

from __future__ import annotations

import logging
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.database import engine
from app.logging_config import (
    LoggingMiddleware,
    redact_url,
    setup_logging,
)

# --- Sentry error tracking ---
if settings.sentry_dsn:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        send_default_pii=False,
        environment="production" if not settings.debug else "development",
    )

from app.models import Base
from app.rate_limiter import limiter
from app.services.monitoring_jobs import MonitoringBackgroundJobs

logger = logging.getLogger("science-ed")

# Log Sentry status after logger is configured
if settings.sentry_dsn:
    logger.info("Sentry error tracking enabled")
else:
    logger.info("Sentry DSN not configured — error tracking disabled")

# Global background jobs instance (started in lifespan, stopped on shutdown)
jobs = MonitoringBackgroundJobs()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle.

    On startup:
        - Verifies database connectivity (logs CRITICAL if unreachable).
        - Reports model count loaded by SQLAlchemy.
        - Logs startup time and redacted DB URL.
        - Starts monitoring background jobs.
    On shutdown:
        - Disposes the connection pool.
    """
    startup_ts = _time.time()

    # ------------------------------------------------------------------
    # Startup self‑check
    # ------------------------------------------------------------------
    logger.info(
        "Starting up",
        extra={
            "host": settings.host,
            "port": settings.port,
            "debug": settings.debug,
            "db_url": redact_url(settings.database_url),
            "log_level": settings.log_level,
        },
    )

    # --- DB connectivity check ---
    db_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        db_ok = True
        logger.info("Database connection verified")
    except Exception as exc:
        logger.critical(
            "Database connectivity check failed — will retry on first request",
            extra={
                "db_url": redact_url(settings.database_url),
                "error": str(exc),
            },
            exc_info=True,
        )

    # Create tables if DB is reachable (best-effort; Alembic manages production schemas)
    if db_ok:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:
            logger.warning(
                "Table creation skipped — schema may already exist or be managed by Alembic",
                extra={"error": str(exc)},
            )

    # --- Model count ---
    try:
        model_count = len(Base.metadata.tables)
        logger.info("Models loaded", extra={"model_count": model_count})
    except Exception as exc:
        logger.warning("Could not count models", extra={"error": str(exc)})

    elapsed = _time.time() - startup_ts
    logger.info("Startup complete", extra={"startup_seconds": round(elapsed, 3)})

    # --- Start background jobs ---
    async with jobs.start():
        yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Shutting down — disposing engine")
    await engine.dispose()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

# Must happen before any other code logs
setup_logging(level=settings.log_level)

app = FastAPI(
    title="ScienceEd API",
    description="Backend for the adaptive science learning platform — "
    "provides session tracking, event ingestion, AI feedback, "
    "student progress tracking, and teacher dashboard endpoints.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- CORS (order matters: CORS before our logging middleware) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Structured logging middleware ---
app.add_middleware(LoggingMiddleware)

# --- Static Files (Teacher Dashboard Pages) ---
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- Rate Limiting ---
app.state.limiter = limiter


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom 429 handler that returns Retry-After header."""
    response = JSONResponse(
        {"error": f"Rate limit exceeded: {exc.detail}"},
        status_code=429,
        headers={"Retry-After": "60"},
    )
    return response


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# --- Routers (lazy import — keep them after middleware setup) ---
from app.routers import (  # noqa: E402
    health,
    sessions,
    events,
    feedback,
    student,
    teacher,
    auth,
    admin,
    bkt,
    monitoring,
    recommendation,
)

app.include_router(health.router)
app.include_router(health.v1_router)
app.include_router(sessions.router)
app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(teacher.class_overview_router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(bkt.router)
app.include_router(monitoring.router)
app.include_router(recommendation.router)
