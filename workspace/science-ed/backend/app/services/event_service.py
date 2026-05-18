"""Event ingestion service — validates session, batch-inserts events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, SessionModel
from app.schemas.extra_data import ALLOWED_EVENT_KEYS, validate_extra_data_dict


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
    # Convert UUIDs to strings for SQLite compatibility:
    # models use PostgreSQL UUID type which doesn't bind correctly on SQLite.
    sid = str(session_id)

    # --- Validate session exists ---
    result = await db.execute(
        select(SessionModel.id).where(SessionModel.id == sid)
    )
    if result.scalar_one_or_none() is None:
        raise ValueError(f"Session {session_id} does not exist")

    # --- Build Event ORM instances ---
    rows = [
        Event(
            session_id=sid,
            student_id=str(student_id) if student_id else None,
            sim_id=str(sim_id) if sim_id else None,
            event_type=ev["event_type"],
            event_name=ev.get("event_name"),
            event_value=ev.get("event_value"),
            client_ts=ev["client_ts"],
            extra_data=validate_extra_data_dict(
                ev.get("extra_data", {}), ALLOWED_EVENT_KEYS, "Event.extra_data"
            ),
        )
        for ev in events
    ]

    db.add_all(rows)
    await db.flush()  # commit happens in the caller's get_db context manager

    return len(rows)
