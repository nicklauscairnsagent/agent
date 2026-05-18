"""Events router — POST /api/v1/events/batch for real DB-backed ingestion."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import EventBatchRequest, EventBatchResponse
from app.services.event_service import ingest_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.post(
    "/batch",
    response_model=EventBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a batch of interaction events",
    description="Ingest a batch of interaction events for a given session. "
    "Validates that the session_id exists before inserting. "
    "Returns the count of ingested events.",
)
async def events_batch(body: EventBatchRequest, db: AsyncSession = Depends(get_db)) -> EventBatchResponse:
    """Ingest a batch of interaction events for a given session.

    Validates that the session_id exists before inserting.
    Returns the count of ingested events.
    """
    events_dicts = [ev.model_dump(mode="python") for ev in body.events]

    try:
        ingested = await ingest_events(
            db=db,
            session_id=body.session_id,
            events=events_dicts,
        )
    except ValueError:
        # Session not found — generic message per compliance Finding 2.4
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    logger.info("Ingested %d events for session %s", ingested, body.session_id)

    return EventBatchResponse(
        ingested=ingested,
        session_id=body.session_id,
    )
