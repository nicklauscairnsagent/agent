"""Simple in-memory sliding window rate limiter for admin export endpoints.

Uses a dict-based approach — no Redis dependency. Each user gets a window
of ``limit`` requests per ``window_seconds``. Works per-user (by user_id).

NOTE: Not distributed-safe. Fine for single-process FastAPI deployments.
If we add Redis later, swap this for a Redis-backed implementation.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.dependencies import require_role

# Defaults for heavy export endpoints
EXPORT_LIMIT: int = 10         # requests per window
EXPORT_WINDOW: int = 60        # seconds


@dataclass
class _SlidingWindowStore:
    """In-memory sliding window store, keyed by user_id.

    Thread-safe enough for async — any concurrent access within the same event
    loop is serialised. For multi-worker deployments, use Redis.
    """
    _windows: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def _prune(self, key: str, window: int, now: float) -> None:
        cutoff = now - window
        self._windows[key] = [ts for ts in self._windows[key] if ts > cutoff]

    def allow(self, key: str, limit: int, window: int, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        self._prune(key, window, now)
        hits = self._windows[key]
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


_store = _SlidingWindowStore()


def rate_limit_exports(
    limit: int = EXPORT_LIMIT,
    window: int = EXPORT_WINDOW,
) -> Callable:
    """Factory: return a dependency that rate-limits by user.

    Usage:
        @router.get("/export/students")
        async def export_students(
            _user=Depends(require_role("admin")),
            _rate=Depends(rate_limit_exports()),
            ...
        ):
    """

    async def _rate_checker(
        current_user=Depends(require_role("admin")),
    ) -> None:
        if not _store.allow(current_user.id, limit, window):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} requests per {window}s",
            )

    return _rate_checker
