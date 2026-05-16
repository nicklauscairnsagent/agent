"""
ScienceEd Backend — FastAPI Application

A self-hosted tracking, AI-feedback, and teacher-dashboard backend
for the Nicklaus Cairns interactive science simulation platform.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
from app.models import Base


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    # Startup: create tables (works for SQLite; on PostgreSQL use Alembic)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        # Log but don't crash — the DB may not be reachable yet
        pass
    yield
    # Shutdown: dispose engine
    await engine.dispose()


app = FastAPI(
    title="ScienceEd API",
    description="Backend for the adaptive science learning platform — "
    "provides session tracking, event ingestion, AI feedback, "
    "student progress tracking, and teacher dashboard endpoints.",
    version="0.1.0",
    lifespan=lifespan,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
from app.routers import health, sessions, events, feedback, student, teacher, auth, admin

app.include_router(health.router)
app.include_router(health.v1_router)
app.include_router(sessions.router)
app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(student.router)
app.include_router(teacher.router)
app.include_router(auth.router)
app.include_router(admin.router)
