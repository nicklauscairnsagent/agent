"""NGSS Tasks and Standards Documentation Router — teacher/admin only.

Serves NGSS task content from the Jekyll ``_includes/tasks/`` directory and
NGSS standards documentation from ``en/ngss/``, gated behind authentication
with teacher/admin role checking.

Endpoints:
    GET /api/v1/ngss/tasks          — List all NGSS tasks (teacher/admin only)
    GET /api/v1/ngss/tasks/{slug}   — Get task content (teacher/admin only)
    GET /api/v1/ngss/standards      — List NGSS standards docs (teacher/admin only)
    GET /api/v1/ngss/standards/{slug} — Get standards doc (teacher/admin only)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.database import get_db  # noqa: F401 — kept for dependency compatibility
from app.dependencies import get_optional_user
from app.models import User
from app.schemas.task import (
    NGSSStandardDetailResponse,
    NGSSStandardListResponse,
    NGSSStandardSummary,
    TaskDetailResponse,
    TaskListResponse,
    TaskSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ngss", tags=["sims"])

# ── Helpers ─────────────────────────────────────────────────────────────


def _parse_title_from_markdown(content: str) -> str | None:
    """Extract the first ``## Title`` heading from markdown content."""
    match = re.search(r"^##\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_estimated_time_from_markdown(content: str) -> str | None:
    """Extract **Estimated Time:** value from markdown content."""
    match = re.search(r"\*\*Estimated Time:\*\*\s*(.+)", content)
    return match.group(1).strip() if match else None


def _get_task_slug(filename: str) -> str:
    """Extract the slug from a task filename like ``bond-energy-task.md``."""
    name = filename.rsplit(".", 1)[0]
    # Remove locale suffix and -task suffix
    for suffix in ("-task-es", "-task"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _get_task_locale(filename: str) -> str:
    """Determine locale from filename: ``*-es`` = es, else en."""
    name = filename.rsplit(".", 1)[0]
    return "es" if name.endswith("-es") else "en"


# ── Auth helper ──────────────────────────────────────────────────────


async def _require_teacher_or_admin(
    current_user: User | None,
) -> User:
    """Enforce teacher/admin role. Returns the user if authorized.

    Must be called after ``get_optional_user`` — raises 401/403 as needed.
    Matches the error format from the existing sims ngss-task endpoint.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Authentication required",
                "message": "NGSS documentation is available to teachers and administrators only. "
                "Please log in or register.",
                "auth_required": True,
                "login_url": settings.frontend_login_url,
                "register_url": settings.frontend_register_url,
            },
        )

    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and administrators can access this resource",
        )

    return current_user


# ── NGSS Task Endpoints ────────────────────────────────────────────────


@router.get(
    "/tasks",
    response_model=TaskListResponse,
    summary="List all NGSS tasks (teacher/admin only)",
    description="Returns a list of all available NGSS task content files. "
    "Only teachers and administrators can access this. "
    "Unauthenticated users receive 401, authenticated students receive 403.",
    responses={
        200: {"description": "List of NGSS tasks"},
        401: {"description": "Authentication required"},
        403: {"description": "Only teachers and administrators can access this resource"},
    },
)
async def list_ngss_tasks(
    current_user: User | None = Depends(get_optional_user),
) -> TaskListResponse:
    """List all available NGSS tasks — teacher/admin only."""
    user = await _require_teacher_or_admin(current_user)

    tasks_dir = Path(settings.tasks_content_dir)
    if not tasks_dir.exists():
        return TaskListResponse(tasks=[], total=0, role=user.role)

    summaries: list[TaskSummaryResponse] = []
    for fpath in sorted(tasks_dir.glob("*-task.md")):
        slug = _get_task_slug(fpath.name)
        locale = _get_task_locale(fpath.name)
        content = fpath.read_text(encoding="utf-8")
        title = _parse_title_from_markdown(content)
        estimated_time = _parse_estimated_time_from_markdown(content)

        summaries.append(
            TaskSummaryResponse(
                slug=slug,
                title=title,
                locale=locale,
                estimated_time=estimated_time,
            )
        )

    return TaskListResponse(tasks=summaries, total=len(summaries), role=user.role)


@router.get(
    "/tasks/{slug}",
    response_model=TaskDetailResponse,
    summary="Get NGSS task content (teacher/admin only)",
    description="Returns the full markdown content of a specific NGSS task. "
    "Only teachers and administrators can access this. "
    "Unauthenticated users receive 401, authenticated students receive 403.",
    responses={
        200: {"description": "Task content"},
        401: {"description": "Authentication required"},
        403: {"description": "Only teachers and administrators can access this resource"},
        404: {"description": "Task not found"},
    },
)
async def get_ngss_task_content(
    slug: str,
    current_user: User | None = Depends(get_optional_user),
) -> TaskDetailResponse:
    """Get a specific NGSS task's full content — teacher/admin only."""
    user = await _require_teacher_or_admin(current_user)

    # Try English first, then Spanish
    tasks_dir = Path(settings.tasks_content_dir)
    candidates = [
        tasks_dir / f"{slug}-task.md",
        tasks_dir / f"{slug}-task-es.md",
    ]

    fpath = None
    locale = "en"
    for candidate in candidates:
        if candidate.exists():
            fpath = candidate
            locale = _get_task_locale(candidate.name)
            break

    if fpath is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{slug}' not found",
        )

    content = fpath.read_text(encoding="utf-8")
    title = _parse_title_from_markdown(content)
    estimated_time = _parse_estimated_time_from_markdown(content)

    return TaskDetailResponse(
        slug=slug,
        title=title,
        content_markdown=content,
        locale=locale,
        estimated_time=estimated_time,
        role=user.role,
    )


# ── NGSS Standards Documentation Endpoints ─────────────────────────────


@router.get(
    "/standards",
    response_model=NGSSStandardListResponse,
    summary="List NGSS standards documentation (teacher/admin only)",
    description="Returns a list of NGSS standards documentation pages "
    "(performance expectations, evidence statements, etc.). "
    "Only teachers and administrators can access this. "
    "Unauthenticated users receive 401, authenticated students receive 403.",
    responses={
        200: {"description": "List of NGSS standards docs"},
        401: {"description": "Authentication required"},
        403: {"description": "Only teachers and administrators can access this resource"},
    },
)
async def list_ngss_standards(
    current_user: User | None = Depends(get_optional_user),
) -> NGSSStandardListResponse:
    """List all NGSS standards documentation pages — teacher/admin only."""
    user = await _require_teacher_or_admin(current_user)

    ngss_dir = Path(settings.ngss_content_dir)
    if not ngss_dir.exists():
        return NGSSStandardListResponse(standards=[], total=0, role=user.role)

    summaries: list[NGSSStandardSummary] = []
    # Collect subdirectories with index.md
    for item in sorted(ngss_dir.iterdir()):
        if item.is_dir():
            index_file = item / "index.md"
            if index_file.exists():
                # Parse the title from frontmatter or directory name
                title = _parse_title_from_index(index_file)
                slug = item.name
                # Determine category from parent structure
                category = slug.replace("-", " ").title()
                summaries.append(
                    NGSSStandardSummary(
                        slug=slug,
                        title=title or slug.replace("-", " ").title(),
                        category=category,
                        has_pdf=False,
                        locale="en",
                    )
                )
        elif item.suffix == ".pdf":
            slug = item.stem
            title = slug.replace("-", " ").title()
            summaries.append(
                NGSSStandardSummary(
                    slug=slug,
                    title=title,
                    category="PDF Document",
                    has_pdf=True,
                    locale="en",
                )
            )

    return NGSSStandardListResponse(
        standards=summaries,
        total=len(summaries),
        role=user.role,
    )


def _parse_title_from_index(index_path: Path) -> str | None:
    """Parse the ``title`` field from a Jekyll index.md frontmatter."""
    content = index_path.read_text(encoding="utf-8")
    match = re.search(r"^title:\s*(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip().strip('"').strip("'")
    return None


@router.get(
    "/standards/{slug}",
    response_model=NGSSStandardDetailResponse,
    summary="Get NGSS standards documentation page (teacher/admin only)",
    description="Returns the full content of an NGSS standards documentation page. "
    "Only teachers and administrators can access this. "
    "Unauthenticated users receive 401, authenticated students receive 403.",
    responses={
        200: {"description": "Standards documentation content"},
        401: {"description": "Authentication required"},
        403: {"description": "Only teachers and administrators can access this resource"},
        404: {"description": "Documentation page not found"},
    },
)
async def get_ngss_standard(
    slug: str,
    current_user: User | None = Depends(get_optional_user),
) -> NGSSStandardDetailResponse:
    """Get a specific NGSS standards documentation page — teacher/admin only."""
    user = await _require_teacher_or_admin(current_user)

    ngss_dir = Path(settings.ngss_content_dir)

    # Try as a directory with index.md
    index_file = ngss_dir / slug / "index.md"
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        title = _parse_title_from_index(index_file) or slug.replace("-", " ").title()
        return NGSSStandardDetailResponse(
            slug=slug,
            title=title,
            content_markdown=content,
            category=slug.replace("-", " ").title(),
            locale="en",
            role=user.role,
        )

    # Try as a PDF
    pdf_file = ngss_dir / f"{slug}.pdf"
    if pdf_file.exists():
        return NGSSStandardDetailResponse(
            slug=slug,
            title=slug.replace("-", " ").title(),
            content_markdown="",
            content_pdf_url=f"{settings.github_pages_url}/en/ngss/{slug}.pdf",
            category="PDF Document",
            locale="en",
            role=user.role,
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"NGSS standard '{slug}' not found",
    )
