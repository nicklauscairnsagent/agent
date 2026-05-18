from pydantic import BaseModel, ConfigDict, EmailStr, Field, UUID4
from typing import Optional


class MagicLinkRequest(BaseModel):
    """Request a magic link for passwordless login."""

    email: EmailStr
    role: Optional[str] = None  # 'student', 'teacher', 'admin'


class MagicLinkResponse(BaseModel):
    """Confirmation that a magic link email was sent."""

    status: str = "sent"
    message: str

    model_config = ConfigDict(from_attributes=True)


class VerifyTokenRequest(BaseModel):
    """Verify a magic link token to exchange for a session JWT."""

    token: str


class VerifyTokenResponse(BaseModel):
    """JWT tokens returned after successful verification — no PII exposed."""

    access_token: str
    refresh_token: str
    expires_in: int

    model_config = ConfigDict(from_attributes=True)


class UserProfileResponse(BaseModel):
    """PII-safe user profile returned from the authenticated /me endpoint."""

    id: str
    email: str | None = None
    display_name: str | None = None
    role: str
    username: str | None = None
    avatar_url: str | None = None
    created_at: str | None = None
    account_status: str = "active"

    model_config = ConfigDict(from_attributes=True)


class TeacherRegisterRequest(BaseModel):
    """Request body for teacher registration."""

    email: EmailStr
    password: str
    name: str
    school: str | None = None
    subject: str | None = None
    birth_year: int | None = Field(None, ge=1900, le=2026)


class TeacherRegisterResponse(BaseModel):
    """Response returned after successful teacher registration."""

    id: UUID4
    email: str
    name: str
    role: str = "teacher"
    school: str | None = None
    subject: str | None = None
    message: str = "Account created successfully. Check your email to verify your account."

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """Login with email and password."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """JWT tokens returned after successful login."""

    access_token: str
    refresh_token: str
    expires_in: int
    user: UserProfileResponse

    model_config = ConfigDict(from_attributes=True)


# ── Student Registration (COPPA B1) ───────────────────────────────────


class StudentRegisterRequest(BaseModel):
    """Request body for student registration with age verification."""

    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=8)
    display_name: str | None = None
    birth_year: int | None = Field(None, ge=1900, le=2026)


class StudentRegisterResponse(BaseModel):
    """Response returned after student registration — differs based on age gate."""

    id: str
    username: str
    email: str
    display_name: str | None = None
    role: str = "student"
    account_status: str = "active"
    message: str = "Account created successfully."
    parental_consent_required: bool = False

    model_config = ConfigDict(from_attributes=True)


# ── Parental Consent (COPPA B1) ──────────────────────────────────────


class ParentalConsentVerifyRequest(BaseModel):
    """Verifies parental consent for an under-13 account."""

    consent_token: str
    method: str = Field(default="email", pattern=r"^(email|video|signed_form)$")


class ParentalConsentVerifyResponse(BaseModel):
    """Response after successful parental consent verification."""

    status: str = "consent_recorded"
    message: str = "Parental consent verified. Your account is now active."
    user_id: str | None = None


class ParentalConsentStatusResponse(BaseModel):
    """Check the status of a pending consent request."""

    account_status: str
    message: str
