"""Schemas for simulation endpoints — auth-gated metadata vs. full content."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# ── Public metadata (returned for ALL users, including unauthenticated) ──


class SimMetadataResponse(BaseModel):
    """Public sim metadata for listings and search results."""

    id: str
    slug: str
    title_en: str
    title_es: str | None = None
    category_slug: str
    category_en: str
    category_es: str | None = None
    description_en: str | None = None
    description_es: str | None = None
    thumbnail: str | None = None
    difficulty: int = 5
    ngss_standards: list[str] = []
    has_task: bool = False
    url_en: str
    url_es: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SimListResponse(BaseModel):
    """List of sims — always public."""

    sims: list[SimMetadataResponse]
    total: int
    authenticated: bool = False


# ── Full detail (authenticated only) ──


class SimFullContent(BaseModel):
    """Full sim content/config returned to authenticated users."""

    config: dict[str, Any] = {}
    skills: list[str] | None = None
    prerequisites: list[str] = []
    task_slugs: list[str] = []
    extra_data: dict[str, Any] = {}


class SimDetailResponse(BaseModel):
    """Sim detail — metadata for all, full content only if authenticated."""

    metadata: SimMetadataResponse
    authenticated: bool
    content: SimFullContent | None = None
    login_url: str | None = None
    register_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Launch endpoint ──


class SimLaunchResponse(BaseModel):
    """Sim launch response — returns metadata for all, full content only if authenticated."""

    metadata: SimMetadataResponse
    authenticated: bool
    content: SimFullContent | None = None
    login_url: str | None = None
    register_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Search ──


class SimSearchResponse(BaseModel):
    """Search results — always public metadata only."""

    results: list[SimMetadataResponse]
    total: int
    query: str = ""
    authenticated: bool = False


# ── NGSS Task access ──


class NGSSTaskAccessResponse(BaseModel):
    """NGSS task page response — gated by role."""

    allowed: bool
    role: str
    task_content: dict[str, Any] | None = None
    message: str | None = None


# ── Error response (matching requirement spec) ──


class AuthRequiredResponse(BaseModel):
    """401 response body for unauthenticated sim endpoint access."""

    error: str = "Authentication required"
    message: str = "Please log in or register to use simulations"
    auth_required: bool = True
    login_url: str | None = None
    register_url: str | None = None
