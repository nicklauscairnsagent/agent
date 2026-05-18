"""
Application-wide shared state for monitoring and observability.

Singleton values accessible across the FastAPI process.
Not thread-safe — intended for single-process async apps.
"""

from __future__ import annotations

from datetime import datetime, timezone

_last_monitoring_tick: datetime | None = None


def get_last_monitoring_tick() -> datetime | None:
    """Return the UTC timestamp of the last background monitoring job run."""
    return _last_monitoring_tick


def set_last_monitoring_tick(tick: datetime | None = None) -> None:
    """Record a monitoring job tick.

    Uses current UTC time by default. Future background jobs should call this
    at the end of each successful run so the health endpoint can report it.
    """
    global _last_monitoring_tick  # noqa: PLW0603
    _last_monitoring_tick = tick or datetime.now(timezone.utc)
