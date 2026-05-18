"""
ScienceEd Backend — FastAPI Application

A self-hosted tracking, AI-feedback, and teacher-dashboard backend
for the interactive science simulation platform.

Observability:
    - Structured JSON logging via LoggingMiddleware (method, path, status, duration, IP)
    - Startup self-check: DB connectivity, model count, startup time
    - Health endpoints at /health and /api/v1/health
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text as sql_text

from app.config import settings
from app.database import engine
from app.logging_config import (
    LoggingMiddleware,
    redact_url,
    sentry_before_send,
    setup_logging,
)

logger = logging.getLogger("science-ed")


def _get_git_revision() -> str | None:
    """Return the short git commit hash, or None if unavailable."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup / shutdown lifecycle.

    On startup:
        - Initializes Sentry error tracking (if SENTRY_DSN configured).
        - Verifies database connectivity (logs CRITICAL if unreachable).
        - Reports model count loaded by SQLAlchemy.
        - Logs startup time and redacted DB URL.
    On shutdown:
        - Disposes the connection pool.
    """
    import os
    import time as _time

    startup_ts = _time.time()

    # ------------------------------------------------------------------
    # Sentry error tracking (production only — skip if DSN absent)
    # ------------------------------------------------------------------
    sentry_dsn = os.environ.get("SENTRY_DSN", "")
    if sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
            release=_get_git_revision(),
            before_send=sentry_before_send,
        )
        logger.info("Sentry error tracking initialized", extra={"traces_sample_rate": 0.1})
    else:
        logger.info("Sentry DSN not set — error tracking disabled")

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

    try:
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as exc:
        logger.critical(
            "Database unreachable — shutting down",
            extra={
                "db_url": redact_url(settings.database_url),
                "error": str(exc),
            },
            exc_info=True,
        )
        raise SystemExit(1) from exc

    # Count registered ORM models
    try:
        from app.models import Base

        model_count = len(Base.metadata.tables)
        logger.info("Models loaded", extra={"model_count": model_count})
    except Exception as exc:
        logger.warning("Could not count models", extra={"error": str(exc)})

    elapsed = _time.time() - startup_ts
    logger.info("Startup complete", extra={"startup_seconds": round(elapsed, 3)})

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
    contact={
        "name": "ScienceEd Support",
        "url": "https://sims.science",
        "email": "support@sims.science",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "health",
            "description": "Health check endpoints — verify the API and database are operational.",
        },
        {
            "name": "sessions",
            "description": "Learning session management — start/end sessions for sim interactions.",
        },
        {
            "name": "events",
            "description": "Interaction event ingestion — batch-upload tracking events from the SDK.",
        },
        {
            "name": "feedback",
            "description": "AI feedback and hint generation — request contextual hints and rate their helpfulness.",
        },
        {
            "name": "student",
            "description": "Student account & progress — view skill states, claim anon data, request deletion.",
        },
        {
            "name": "teacher",
            "description": "Teacher dashboard — class rosters, student analytics, sim assignments, insights.",
        },
        {
            "name": "auth",
            "description": "Authentication — magic-link login, JWT token management, user profiles.",
        },
        {
            "name": "admin",
            "description": "Administration — system stats, catalog sync, and platform maintenance endpoints.",
        },
        {
            "name": "parent",
            "description": "Parent/guardian data access — view and export child's educational records (FERPA/COPPA B2).",
        },
        {
            "name": "sims",
            "description": "Simulation catalog — search, listing, launch, and NGSS task endpoints. Public metadata; full content requires authentication.",
        },
    ],
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,  # Hide schemas by default for cleaner UI
        "docExpansion": "list",
        "persistAuthorization": True,
    },
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

# --- Routers (lazy import — keep them after middleware setup) ---
from app.routers import health, sessions, events, feedback, student, teacher, auth, admin, parent, sims, tasks

app.include_router(health.router)
app.include_router(health.v1_router)
app.include_router(sessions.router)
app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(parent.router)
app.include_router(sims.router)
app.include_router(tasks.router)


# ---------------------------------------------------------------------------
# OpenAPI customization
# ---------------------------------------------------------------------------

def custom_openapi() -> dict:
    """Generate the OpenAPI schema with JWT Bearer security scheme injected."""
    if app.openapi_schema:
        return app.openapi_schema

    # Call the original FastAPI.openapi() method to avoid recursion
    openapi_schema = FastAPI.openapi(app)
    if openapi_schema is None:
        openapi_schema = {}

    # Security scheme
    openapi_schema.setdefault("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT access token. "
            "Get one from `/api/v1/auth/verify-token` "
            "after requesting a magic link. Format: `Bearer <token>`",
        }
    }

    # Apply global security (all endpoints require Bearer by default)
    openapi_schema["security"] = [{"BearerAuth": []}]

    # Public endpoints that don't require authentication
    public_paths = {
        ("/health", "get"),
        ("/api/v1/health", "get"),
        ("/api/v1/session/start", "post"),
        ("/api/v1/events/batch", "post"),
        ("/api/v1/auth/request-magic-link", "post"),
        ("/api/v1/auth/verify-token", "post"),
        ("/api/v1/auth/teacher/register", "post"),
    }

    # Sim endpoints: public (no Bearer badge) — auth is optional, described in endpoint docs
    sim_public_paths = {
        ("/api/v1/sims", "get"),
        ("/api/v1/sims/search", "get"),
    }

    # Sim detail & launch: single-param paths match pattern /api/v1/sims/{sim_id}
    # and /api/v1/sims/{sim_id}/launch. NGSS task /api/v1/sims/{sim_id}/ngss-task
    # requires auth so it keeps the Bearer badge.

    # NGSS task/standards endpoints require auth (keep Bearer badge)
    ngss_protected_paths = {
        ("/api/v1/ngss/tasks", "get"),
        ("/api/v1/ngss/standards", "get"),
    }

    for path, path_item in openapi_schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if (path, method) in public_paths:
                operation["security"] = []
            # Sim list/search are public (no bearer badge)
            if (path, method) in sim_public_paths:
                operation["security"] = []
            # Sim detail and launch paths: /api/v1/sims/{sim_id} and /api/v1/sims/{sim_id}/launch
            # Accept optional Bearer but don't require it — check by path prefix + method
            if path.startswith("/api/v1/sims/") and method in ("get",):
                # Skip ngss-task (requires auth) and paths with more than 2 segments after /sims/
                segments = path[len("/api/v1/sims/"):].split("/")
                if len(segments) <= 2:
                    # Only clear for detail (1 segment) and launch (2 segments)
                    if len(segments) == 1 or (len(segments) == 2 and segments[1] == "launch"):
                        operation["security"] = []

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
