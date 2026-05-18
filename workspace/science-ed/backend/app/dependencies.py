"""FastAPI dependencies for JWT authentication and authorization.

Provides:
- get_current_user: Extracts and validates JWT from Authorization header
- get_optional_user: Extracts JWT if present, returns None otherwise (no 401)
- require_role(role): Factory that requires a specific user role
- require_teacher_or_admin: Requires role 'teacher' or 'admin'
- OwnerOrTeacher: Verifies user owns the requested resource OR is a teacher
- TeacherOfClass: Verifies user is the teacher of a specific class
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Header, WebSocket, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, ClassModel, Enrollment

logger = logging.getLogger(__name__)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT from Authorization: Bearer header.

    Returns the User model instance matching the JWT 'sub' claim.
    Raises 401 if the token is missing, expired, or invalid.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format — expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        logger.warning("JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Extract and validate JWT from Authorization header — returns None if missing/invalid.

    Unlike ``get_current_user``, this dependency does NOT raise 401.
    Returns the User model if a valid token is provided, None otherwise.
    Use this for endpoints that behave differently for authenticated vs. anonymous users.
    """
    if authorization is None:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None

    user_id: str | None = payload.get("sub")
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or user.deleted_at is not None:
        return None

    return user


def require_role(required_role: str):
    """Factory: return a dependency that requires the user to have a specific role.

    Usage:
        @router.get("/admin/sims")
        async def admin_sims(user: User = Depends(require_role("admin"))):
            ...
    """

    async def _role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{required_role}'",
            )
        return current_user

    return _role_checker


async def require_teacher_or_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user to have role 'teacher' or 'admin'.

    Usage for NGSS task endpoints:
        @router.get("/ngss-tasks/{task_id}")
        async def get_ngss_task(user: User = Depends(require_teacher_or_admin)):
            ...
    """
    if current_user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and administrators can access this resource",
        )
    return current_user


async def OwnerOrTeacher(
    id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify the authenticated user owns the resource OR is their teacher.

    Used for student-specific endpoints (progress, skill state).
    The 'id' parameter is the student/user ID in the path.
    Teachers can access data of students enrolled in their classes.
    """
    # Same user — always allowed
    if current_user.id == id:
        return current_user

    # Teacher — check if student is in one of their classes
    if current_user.role == "teacher":
        # Find if the target student is enrolled in any class owned by this teacher
        result = await db.execute(
            select(Enrollment)
            .join(ClassModel, ClassModel.id == Enrollment.class_id)
            .where(
                ClassModel.teacher_id == current_user.id,
                Enrollment.student_id == id,
            )
            .limit(1)
        )
        enrollment = result.scalar_one_or_none()
        if enrollment is not None:
            return current_user

    # Admin — full access
    if current_user.role == "admin":
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this resource",
    )


async def TeacherOfClass(
    class_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify the authenticated user is the teacher of the specified class."""
    result = await db.execute(
        select(ClassModel).where(
            ClassModel.id == class_id,
            ClassModel.teacher_id == current_user.id,
        )
    )
    cls = result.scalar_one_or_none()

    if cls is None and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not the teacher of this class",
        )

    return current_user


async def get_ws_user(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Authenticate a WebSocket connection via query parameter token.

    Reads the ``token`` query parameter, decodes the JWT, and returns
    the ``User`` model. Returns ``None`` on failure (caller should close).
    """
    from jose import JWTError, jwt

    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return None

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        await websocket.close(code=4001, reason="Invalid token")
        return None

    user_id: str | None = payload.get("sub")
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token payload")
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        await websocket.close(code=4001, reason="User not found")
        return None

    return user
