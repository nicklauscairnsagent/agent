"""Sims router — simulation listing, launch, and NGSS task endpoints with auth gating.

All sim endpoints use the optional auth dependency ``get_optional_user`` to
distinguish public access (metadata-only) from authenticated access (full content).

Auth flow:
- Sim listing/search: always public (metadata only)
- Sim launch: returns metadata for all, full content/config only if authenticated
- NGSS task endpoints: require teacher or admin role (student → 403, unauth → 401)
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_optional_user
from app.models import Sim, User
from app.schemas import (
    SimMetadataResponse,
    SimListResponse,
    SimFullContent,
    SimDetailResponse,
    SimLaunchResponse,
    SimSearchResponse,
    AuthRequiredResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sims", tags=["sims"])


# ── Helper: build SimMetadataResponse from ORM model ──────────────────


def _to_metadata(sim: Sim) -> SimMetadataResponse:
    """Convert a Sim ORM instance to a public metadata response."""
    return SimMetadataResponse(
        id=sim.id,
        slug=sim.slug,
        title_en=sim.title_en,
        title_es=sim.title_es,
        category_slug=sim.category_slug,
        category_en=sim.category_en,
        category_es=sim.category_es,
        description_en=sim.description_en,
        description_es=sim.description_es,
        thumbnail=sim.extra_data.get("thumbnail") if isinstance(sim.extra_data, dict) else None,
        difficulty=sim.difficulty,
        ngss_standards=sim.ngss_standards,
        has_task=sim.has_task,
        url_en=sim.url_en,
        url_es=sim.url_es,
    )


def _to_full_content(sim: Sim) -> SimFullContent:
    """Convert a Sim ORM instance to full content (authenticated only)."""
    return SimFullContent(
        config=sim.extra_data if isinstance(sim.extra_data, dict) else {},
        skills=sim.skills,
        prerequisites=sim.prerequisites if isinstance(sim.prerequisites, list) else [],
        task_slugs=sim.task_slugs if isinstance(sim.task_slugs, list) else [],
        extra_data=sim.extra_data if isinstance(sim.extra_data, dict) else {},
    )


def _unauthorized_401() -> AuthRequiredResponse:
    """Return the standard 401 response body for unauthenticated access."""
    return AuthRequiredResponse(
        login_url=settings.frontend_login_url,
        register_url=settings.frontend_register_url,
    )


# ── Listing (always public) ───────────────────────────────────────────


@router.get(
    "",
    response_model=SimListResponse,
    summary="List all simulations",
    description="Return metadata for all simulations. No authentication required — powers search/discoverability.",
)
async def sims_list(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """List all simulations with public metadata."""
    result = await db.execute(
        select(Sim).order_by(Sim.title_en)
    )
    sims = result.scalars().all()
    metadata = [_to_metadata(s) for s in sims]
    return SimListResponse(
        sims=metadata,
        total=len(metadata),
        authenticated=current_user is not None,
    )


# ── Search (always public) ────────────────────────────────────────────


@router.get(
    "/search",
    response_model=SimSearchResponse,
    summary="Search simulations",
    description="Search simulations by title, description, category, or NGSS standard. No authentication required.",
)
async def sims_search(
    q: Annotated[str | None, Query(description="Search query")] = None,
    category: Annotated[str | None, Query(description="Filter by category slug")] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Search simulations by keyword or category filter."""
    query = select(Sim).order_by(Sim.title_en)

    if q:
        like_q = f"%{q}%"
        query = query.where(
            or_(
                Sim.title_en.ilike(like_q),
                Sim.title_es.ilike(like_q),
                Sim.description_en.ilike(like_q),
                Sim.description_es.ilike(like_q),
                Sim.category_en.ilike(like_q),
            )
        )

    if category:
        query = query.where(Sim.category_slug == category)

    result = await db.execute(query)
    sims = result.scalars().all()
    metadata = [_to_metadata(s) for s in sims]
    return SimSearchResponse(
        results=metadata,
        total=len(metadata),
        query=q or "",
        authenticated=current_user is not None,
    )


# ── Single sim detail (public metadata, full content if authenticated) ─


@router.get(
    "/{sim_id}",
    response_model=SimDetailResponse,
    summary="Get simulation details",
    description="Return sim metadata for all users. Full content/config only for authenticated users. "
    "Unauthenticated users get login_url and register_url.",
)
async def sims_detail(
    sim_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Get sim details — metadata for all, full content only if authenticated."""
    result = await db.execute(select(Sim).where(Sim.id == sim_id))
    sim = result.scalar_one_or_none()

    if sim is None:
        # Also try by slug
        result = await db.execute(select(Sim).where(Sim.slug == sim_id))
        sim = result.scalar_one_or_none()

    if sim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation not found",
        )

    metadata = _to_metadata(sim)

    if current_user is not None:
        return SimDetailResponse(
            metadata=metadata,
            authenticated=True,
            content=_to_full_content(sim),
        )

    return SimDetailResponse(
        metadata=metadata,
        authenticated=False,
        content=None,
        login_url=settings.frontend_login_url,
        register_url=settings.frontend_register_url,
    )


# ── Launch endpoint ────────────────────────────────────────────────


@router.get(
    "/{sim_id}/launch",
    response_model=SimLaunchResponse,
    summary="Launch a simulation",
    description="Returns sim metadata (public) and full content/config only if authenticated. "
    "Unauthenticated users get login_url and a 200 response with metadata only — no blocking 401.",
    responses={
        404: {"description": "Simulation not found"},
    },
)
async def sims_launch(
    sim_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Launch a simulation.

    Always returns metadata. Only returns full content/config when the
    user is authenticated. Unauthenticated responses include login_url.
    """
    # Look up by id or slug
    result = await db.execute(select(Sim).where(Sim.id == sim_id))
    sim = result.scalar_one_or_none()

    if sim is None:
        result = await db.execute(select(Sim).where(Sim.slug == sim_id))
        sim = result.scalar_one_or_none()

    if sim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation not found",
        )

    return _build_launch_response(sim, current_user is not None, current_user)


def _build_launch_response(
    sim: Sim,
    is_authenticated: bool,
    user: User | None,
) -> SimLaunchResponse:
    """Build a launch response based on auth status."""
    metadata = _to_metadata(sim)

    if is_authenticated:
        return SimLaunchResponse(
            metadata=metadata,
            authenticated=True,
            content=_to_full_content(sim),
        )

    return SimLaunchResponse(
        metadata=metadata,
        authenticated=False,
        content=None,
        login_url=settings.frontend_login_url,
        register_url=settings.frontend_register_url,
    )


# ── NGSS Task Endpoint (teacher/admin only) ────────────────────────


@router.get(
    "/{sim_id}/ngss-task",
    summary="Get NGSS task content (teacher/admin only)",
    description="Returns NGSS task page content. Only teachers and admins can access this. "
    "Students get 403. Unauthenticated users get 401.",
    responses={
        200: {"description": "NGSS task content"},
        401: {
            "description": "Authentication required",
            "content": {
                "application/json": {
                    "example": {
                        "error": "Authentication required",
                        "message": "Please log in or register to use simulations",
                        "auth_required": True,
                        "login_url": "https://sims.science/login",
                        "register_url": "https://sims.science/register",
                    }
                }
            },
        },
        403: {"description": "Only teachers and administrators can access this resource"},
        404: {"description": "Simulation not found"},
    },
)
async def sims_ngss_task(
    sim_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Get NGSS task content — teacher/admin only.

    Unauthenticated → 401 with descriptive JSON body.
    Authenticated student → 403.
    Authenticated teacher/admin → 200 with task content.
    """
    # Check auth first — 401 with descriptive JSON
    if current_user is None:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "Authentication required",
                "message": "Please log in or register to use simulations",
                "auth_required": True,
                "login_url": settings.frontend_login_url,
                "register_url": settings.frontend_register_url,
            },
        )

    # Role check
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and administrators can access this resource",
        )

    # Look up sim by id or slug
    result = await db.execute(select(Sim).where(Sim.id == sim_id))
    sim = result.scalar_one_or_none()

    if sim is None:
        result = await db.execute(select(Sim).where(Sim.slug == sim_id))
        sim = result.scalar_one_or_none()

    if sim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Simulation not found",
        )

    return {
        "allowed": True,
        "role": current_user.role,
        "task_content": {
            "sim_slug": sim.slug,
            "sim_title": sim.title_en,
            "ngss_standards": sim.ngss_standards,
            "task_slugs": sim.task_slugs if isinstance(sim.task_slugs, list) else [],
            "has_prescreener": sim.has_prescreener,
            "has_screener": sim.has_screener,
        },
    }
