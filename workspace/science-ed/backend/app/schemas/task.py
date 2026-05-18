"""Schemas for NGSS task and standards documentation endpoints — teacher/admin only.

These endpoints serve task content from the Jekyll site's ``_includes/tasks/``
directory and NGSS standards docs from ``en/ngss/``, gated behind authentication
with role checking (teacher/admin only).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── NGSS Tasks ──────────────────────────────────────────────────────────


class TaskSummaryResponse(BaseModel):
    """Summary metadata for a single NGSS task (listing view)."""

    slug: str
    title: str | None = None
    sim_slug: str | None = None
    sim_title: str | None = None
    ngss_standards: list[str] = []
    difficulty: int | None = None
    estimated_time: str | None = None
    locale: str = "en"

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Response for listing available NGSS tasks."""

    tasks: list[TaskSummaryResponse]
    total: int
    role: str


class TaskDetailResponse(BaseModel):
    """Full NGSS task content returned to authorized users."""

    slug: str
    title: str | None = None
    content_markdown: str
    locale: str = "en"
    ngss_standards: list[str] = []
    sim_slug: str | None = None
    sim_title: str | None = None
    estimated_time: str | None = None
    role: str


# ── NGSS Standards Documentation ────────────────────────────────────────


class NGSSStandardSummary(BaseModel):
    """Summary for a single NGSS standards documentation page."""

    slug: str
    title: str
    category: str | None = None
    has_pdf: bool = False
    locale: str = "en"

    model_config = ConfigDict(from_attributes=True)


class NGSSStandardListResponse(BaseModel):
    """Response for listing NGSS standards documentation pages."""

    standards: list[NGSSStandardSummary]
    total: int
    role: str


class NGSSStandardDetailResponse(BaseModel):
    """Full NGSS standards documentation page content."""

    slug: str
    title: str
    content_markdown: str
    content_pdf_url: str | None = None
    category: str | None = None
    locale: str = "en"
    role: str
