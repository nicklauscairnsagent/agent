from fastapi import APIRouter, HTTPException, status
from app.schemas import SessionStartRequest, SessionStartResponse, SessionEndRequest, SessionEndResponse

router = APIRouter(prefix="/api/v1/session", tags=["sessions"])


@router.post(
    "/start",
    response_model=SessionStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new learning session",
    description="Create a new learning session when a sim or task page loads. "
    "Returns a session ID, anonymous student token, and expiry time.",
)
async def session_start(body: SessionStartRequest) -> SessionStartResponse:
    # TODO: implement service logic
    return SessionStartResponse(
        session_id="00000000-0000-0000-0000-000000000000",
        student_token="mock-anon-token",
        expires_at="2026-05-17T03:00:00Z",
    )


@router.post(
    "/end",
    response_model=SessionEndResponse,
    summary="End a learning session",
    description="End an active learning session. Optionally report duration and completion status.",
)
async def session_end(body: SessionEndRequest) -> SessionEndResponse:
    # TODO: implement service logic
    return SessionEndResponse(status="ok")
