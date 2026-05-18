"""Auth router — login, registration, token management, user profile, and COPPA age gate."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import (
    MagicLinkRequest,
    MagicLinkResponse,
    UserProfileResponse,
    VerifyTokenRequest,
    VerifyTokenResponse,
    TeacherRegisterRequest,
    TeacherRegisterResponse,
    StudentRegisterRequest,
    StudentRegisterResponse,
    ParentalConsentVerifyRequest,
    ParentalConsentVerifyResponse,
    ParentalConsentStatusResponse,
    LoginRequest,
    LoginResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ── Constants ──────────────────────────────────────────────────────────

_COPPA_MIN_AGE = 13
"""Minimum age without parental consent per COPPA §312.5."""


# ── Helpers ────────────────────────────────────────────────────────────


def _create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token for the given user ID."""
    expire = datetime.now(timezone.utc) + timedelta(
        seconds=settings.jwt_expire_seconds
    )
    to_encode = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def _create_refresh_token() -> str:
    """Create a refresh token (UUID string for now)."""
    return str(uuid4())


def _current_year() -> int:
    """Return the current calendar year."""
    return datetime.now(timezone.utc).year


def _is_under_13(birth_year: int | None) -> bool:
    """Check if a birth year indicates the user is under 13 (COPPA §312.5)."""
    if birth_year is None:
        return False  # no age data = treat as 13+
    return (_current_year() - birth_year) < _COPPA_MIN_AGE


# ── Magic Link Flow ────────────────────────────────────────────────────


@router.post(
    "/request-magic-link",
    response_model=MagicLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a magic link for passwordless login",
    description="Look up or create a user by email and send a one-time magic link. "
    "Auto-registers new users on first request. Currently logs the token "
    "without actually sending an email.",
)
async def auth_request_magic_link(
    body: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a magic link for passwordless login.

    Looks up or creates a user by email, generates a one-time token,
    and (in production) sends an email. Currently returns a success
    response without actually sending email.
    """
    # Upsert user by email
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None:
        # Auto-register new users on magic link request
        user = User(
            email=body.email,
            username=body.email.split("@")[0],
            display_name=body.email.split("@")[0],
            role=body.role or "student",
        )
        db.add(user)
        await db.flush()
        logger.info("Auto-registered user %s with role=%s", user.id, user.role)

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has been deactivated",
        )

    # TODO: actually send magic link email

    return MagicLinkResponse(
        status="sent",
        message="Check your email for the login link",
    )


@router.post(
    "/verify-token",
    response_model=VerifyTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Verify a magic link token and issue JWT",
    description="Validate the one-time token from the magic link "
    "and issue access + refresh JWTs. No PII is returned in this response "
    "- use GET /auth/me to fetch the authenticated user's profile.",
)
async def auth_verify_token(
    body: VerifyTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify a magic link token and return JWT tokens.

    This endpoint validates the one-time token from the magic link
    and issues access + refresh JWTs. No PII (email, name, role)
    is returned in this response — use GET /auth/me to fetch the
    authenticated user's profile.

    If the user's account_status is 'pending_consent', access is denied
    until parental consent is recorded (COPPA §312.5).
    """
    # For now, the token body is a user ID for direct lookup.
    result = await db.execute(select(User).where(User.id == body.token))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deactivated",
        )

    # COPPA age gate: block login for pending_consent accounts
    if user.account_status == "pending_consent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account requires parental consent before you can log in. "
            "Please ask a parent or guardian to check their email for the consent link.",
        )

    access_token = _create_access_token(user.id)
    refresh_token = _create_refresh_token()

    return VerifyTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_seconds,
    )


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get authenticated user profile",
    description="Return the authenticated user's profile (PII-safe, requires valid JWT). "
    "This is the only endpoint that returns personal information "
    "(email, display_name, role).",
)
async def auth_me(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's profile (PII-safe, requires valid JWT)."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        username=current_user.username,
        avatar_url=current_user.avatar_url,
        created_at=(
            current_user.created_at.isoformat()
            if current_user.created_at
            else None
        ),
        account_status=current_user.account_status,
    )


# ── Password Login ─────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Login with email and password",
    description="Authenticate with email and password. Returns JWT access + refresh "
    "tokens and user profile. Supports both password and magic_link auth providers "
    "as long as a password hash exists.",
)
async def auth_login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Login with email and password.

    Looks up the user by email, verifies the password against the
    stored bcrypt hash, and returns JWT tokens with user profile.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been deactivated",
        )

    if user.account_status == "pending_consent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account requires parental consent before you can log in.",
        )

    if user.account_status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled",
        )

    # Verify password
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account does not have a password set. Use magic link login.",
        )

    if not _pwd_context.verify(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = _create_access_token(user.id)
    refresh_token = _create_refresh_token()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_expire_seconds,
        user=UserProfileResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            username=user.username,
            avatar_url=user.avatar_url,
            created_at=user.created_at.isoformat() if user.created_at else None,
            account_status=user.account_status,
        ),
    )


# ── Password hashing ─────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_password(password: str) -> str:
    return _pwd_context.hash(password)


# ── Student Registration (COPPA B1) ────────────────────────────────────


@router.post(
    "/register",
    response_model=StudentRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new student account with age verification",
    description="Create a new student account. If birth_year indicates the user is "
    "under 13, the account is created in 'pending_consent' status and "
    "parental consent is required before login (COPPA §312.5).",
)
async def auth_student_register(
    body: StudentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new student account.

    If ``birth_year`` indicates the user is under 13, the account is created
    with ``account_status='pending_consent'`` and a consent token is generated.
    The user will not be able to log in until parental consent is verified.
    """
    # Check for existing user with this email or username
    result = await db.execute(
        select(User).where(
            (User.email == body.email) | (User.username == body.username)
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email or username already exists",
        )

    # Validate password strength
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    # Hash password
    password_hash = _hash_password(body.password)

    # Determine account status based on age gate
    under_13 = _is_under_13(body.birth_year)
    account_status = "pending_consent" if under_13 else "active"
    parental_consent_id = str(uuid4()) if under_13 else None

    # Create student user
    student = User(
        username=body.username,
        email=body.email,
        display_name=body.display_name or body.username,
        role="student",
        password_hash=password_hash,
        auth_provider="password",
        birth_year=body.birth_year,
        account_status=account_status,
        parental_consent_id=parental_consent_id,
    )
    db.add(student)
    await db.flush()
    logger.info(
        "Registered student %s (%s) — status=%s, birth_year=%s",
        student.id,
        student.email,
        student.account_status,
        student.birth_year,
    )

    # Log the consent token placeholder (no email integration yet)
    if under_13:
        logger.info(
            "PARENTAL_CONSENT_REQUIRED — token=%s, user_id=%s, email=%s",
            parental_consent_id,
            student.id,
            student.email,
        )

    return StudentRegisterResponse(
        id=str(student.id),
        username=student.username,
        email=student.email,
        display_name=student.display_name,
        role=student.role,
        account_status=student.account_status,
        message=(
            "Account created. Parental consent is required before you can log in. "
            "A consent link has been sent to your parent or guardian (placeholder)."
            if under_13
            else "Account created successfully."
        ),
        parental_consent_required=under_13,
    )


# ── Parental Consent (COPPA B1) ────────────────────────────────────────


@router.post(
    "/parental-consent/{consent_token}",
    response_model=ParentalConsentVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify parental consent for an under-13 account",
    description="Verifies a parental consent token and activates the account. "
    "The consent token was generated at registration time and should have been "
    "sent to the parent's email (currently logged).",
)
async def auth_parental_consent(
    consent_token: str,
    body: ParentalConsentVerifyRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Verify parental consent for an under-13 account.

    Looks up the user by ``parental_consent_id``, records the consent
    details, and sets ``account_status`` to 'active'.
    """
    # Find user by their consent token
    result = await db.execute(
        select(User).where(User.parental_consent_id == consent_token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired consent token",
        )

    if user.account_status != "pending_consent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account does not require parental consent",
        )

    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has been deactivated",
        )

    # Record consent
    method = body.method if body else "email"
    user.account_status = "active"
    user.parental_consent_date = datetime.now(timezone.utc)
    user.parental_consent_method = method
    user.consent_given = True
    user.consent_date = datetime.now(timezone.utc)
    user.consent_type = "parental"

    await db.flush()
    logger.info(
        "Parental consent recorded for user %s (%s) — method=%s",
        user.id,
        user.email,
        method,
    )

    return ParentalConsentVerifyResponse(
        status="consent_recorded",
        message="Parental consent verified. Your account is now active.",
        user_id=user.id,
    )


@router.get(
    "/parental-consent/status/{user_id}",
    response_model=ParentalConsentStatusResponse,
    summary="Check parental consent status for a user",
    description="Returns the current account status for a user ID. "
    "Useful for polling whether consent has been recorded.",
)
async def auth_parental_consent_status(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Check the consent status for a given user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.account_status == "pending_consent":
        return ParentalConsentStatusResponse(
            account_status="pending_consent",
            message="Parental consent is still required before this account can be activated.",
        )
    elif user.account_status == "disabled":
        return ParentalConsentStatusResponse(
            account_status="disabled",
            message="This account has been disabled.",
        )

    return ParentalConsentStatusResponse(
        account_status="active",
        message="Account is active.",
    )


# ── Teacher Registration ──────────────────────────────────────────────


@router.post(
    "/teacher/register",
    response_model=TeacherRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new teacher account",
    description="Create a new teacher account with email, password, name, and optional school/subject. "
    "Returns 201 with teacher profile on success. Passwords are hashed with bcrypt.",
)
async def auth_teacher_register(
    body: TeacherRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new teacher account.

    Creates a teacher user with hashed password and optional school/subject
    metadata stored in extra_data. Teachers are assumed to be 13+; the age
    gate does not apply to teachers.
    """
    # Check for existing user with this email
    result = await db.execute(select(User).where(User.email == body.email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Validate password strength
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    # Hash password
    password_hash = _hash_password(body.password)

    # Build extra_data with optional fields
    extra_data = {}
    if body.school:
        extra_data["school"] = body.school
    if body.subject:
        extra_data["subject"] = body.subject

    # Create teacher user
    teacher = User(
        email=body.email,
        username=body.email.split("@")[0],
        display_name=body.name,
        role="teacher",
        password_hash=password_hash,
        auth_provider="password",
        extra_data=extra_data,
        birth_year=body.birth_year,
        account_status="active",  # teachers are always 13+
    )
    db.add(teacher)
    await db.flush()
    logger.info(
        "Registered teacher %s (%s)",
        teacher.id,
        teacher.email,
    )

    # TODO: send verification email

    return TeacherRegisterResponse(
        id=teacher.id,
        email=teacher.email,
        name=teacher.display_name or body.name,
        school=body.school,
        subject=body.subject,
    )
