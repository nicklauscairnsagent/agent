"""Event ingestion service — validates session, batch-inserts events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, SessionModel
from app.schemas.extra_data import EVENT_EXTRA_DATA_KEYS, validate_extra_data_dict


async def ingest_events(
    db: AsyncSession,
    session_id: UUID,
    events: list[dict],
    student_id: UUID | None = None,
    sim_id: UUID | None = None,
) -> int:
    """Ingest a batch of interaction events into the database.

    Validates that *session_id* exists in the ``sessions`` table before
    inserting.  Each dict in *events* must have at least ``event_type``
    and ``client_ts``.

    Returns the number of events successfully inserted.
    """
    # --- Validate session exists ---
    result = await db.execute(
        select(SessionModel.id).where(SessionModel.id == session_id)
    )
    if result.scalar_one_or_none() is None:
        raise ValueError(f"Session {session_id} does not exist")

    # Build Event ORM instances
    rows = [
        Event(
            session_id=session_id,
            student_id=student_id,
            sim_id=sim_id,
            event_type=ev["event_type"],
            event_name=ev.get("event_name"),
            event_value=ev.get("event_value"),
            client_ts=ev["client_ts"],
            locale=ev.get("locale"),
            extra_data=validate_extra_data_dict(
                ev.get("extra_data", {}), "event", EVENT_EXTRA_DATA_KEYS
            ),
        )
        for ev in events
    ]

    db.add_all(rows)
    await db.flush()  # commit happens in the caller's get_db context manager

    return len(rows)
