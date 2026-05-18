"""Student router — progress tracking, skill state, account management."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import OwnerOrTeacher, get_current_user, require_role
from app.models import (
    User,
    DeletionRequest,
    SessionModel,
    Event,
    FeedbackLog,
    SkillState,
    Enrollment,
    ClassModel,
)
from app.schemas import (
    StudentProgressResponse,
    SkillStateResponse,
    ClaimRequest,
    ClaimResponse,
    DeletionRequestCreate,
    DeletionRequestResponse,
    ConsentRequest,
    ConsentResponse,
    StudentProfileData,
    StudentSessionData,
    StudentEventData,
    StudentFeedbackData,
    StudentSkillStateData,
    StudentEnrollmentData,
    StudentDataResponse,
    GenerateParentTokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/student", tags=["student"])


@router.get(
    "/{id}/progress",
    response_model=StudentProgressResponse,
    summary="Get student progress overview",
    description="Get overall progress across all sims for a student. "
    "Requires authentication as the student themselves, their teacher, or an admin.",
)
async def student_progress(
    id: str,
    _auth: User = Depends(OwnerOrTeacher),
):
    """Get overall progress across all sims for a student.

    Requires authentication as the student themselves, their teacher,
    or an admin.
    """
    # TODO: implement real service logic
    return StudentProgressResponse(
        student_id=id,
        total_sims_started=0,
        total_sims_completed=0,
        total_time_spent_minutes=0,
        mastery_by_ngss={},
        recent_sims=[],
        recommended_next=[],
    )


@router.get(
    "/{id}/skill/{skill_id}",
    response_model=SkillStateResponse,
    summary="Get BKT skill state for a student",
    description="Get Bayesian Knowledge Tracing state for a single skill. "
    "Requires authentication as the student themselves, their teacher, or an admin.",
)
async def student_skill(
    id: str,
    skill_id: str,
    _auth: User = Depends(OwnerOrTeacher),
):
    """Get Bayesian Knowledge Tracing state for a single skill.

    Requires authentication as the student themselves, their teacher,
    or an admin.
    """
    # TODO: implement real service logic
    return SkillStateResponse(
        student_id=id,
        skill_id=skill_id,
        know_probability=0.0,
        learning_rate=0.0,
        total_attempts=0,
        correct_attempts=0,
        streak=0,
        last_practiced=None,
        sims_practiced=[],
    )


@router.post(
    "/claim",
    response_model=ClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Claim anonymous session data",
    description="Claim anonymous session data to the authenticated student account. "
    "Merges anonymous sessions (identified by anon_token) into the "
    "currently authenticated student's identity.",
)
async def student_claim(
    body: ClaimRequest,
    current_user: User = Depends(get_current_user),
):
    """Claim anonymous session data to the authenticated student account.

    Merges anonymous sessions (identified by anon_token) into the
    currently authenticated student's identity.
    """
    # TODO: implement real service logic
    return ClaimResponse(
        status="claimed",
        sessions_merged=0,
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def student_delete(
    id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a student account.

    Requires the user to be deleting their own account, or an admin.
    Sets deleted_at timestamp on the user record — does not remove data.
    Returns 204 on success.
    """
    # Only self-deletion or admin
    if current_user.id != id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own account, or use admin privileges",
        )

    result = await db.execute(select(User).where(User.id == id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.deleted_at is not None:
        # Already deleted — idempotent
        return None

    now = datetime.now(timezone.utc)
    await db.execute(
        update(User).where(User.id == id).values(deleted_at=now)
    )
    logger.info("Soft-deleted user %s", id)
    return None


@router.post(
    "/{id}/request-deletion",
    response_model=DeletionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def student_request_deletion(
    id: str,
    body: DeletionRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a deletion request for a student account.

    Logs a request for account deletion (parental/admin workflow).
    Does not delete the account — an authorized user must approve.
    """
    # Verify target user exists
    result = await db.execute(select(User).where(User.id == id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    dr = DeletionRequest(
        user_id=id,
        requested_by=current_user.id,
        reason=body.reason,
        status="pending",
    )
    db.add(dr)
    await db.flush()
    logger.info(
        "Deletion request %s created for user %s by %s",
        dr.id,
        id,
        current_user.id,
    )

    return DeletionRequestResponse(
        id=dr.id,
        user_id=dr.user_id,
        status=dr.status,
        reason=dr.reason,
        created_at=dr.created_at.isoformat() if dr.created_at else None,
    )


# ─── Consent Tracking (FERPA/COPPA B4) ──────────────────────────────────────


@router.get(
    "/me/consent",
    response_model=ConsentResponse,
    summary="Get current consent state",
    description="Return the authenticated student's current consent tracking state. "
    "FERPA/COPPA compliance endpoint (Finding B4).",
)
async def get_my_consent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's consent tracking state.

    Returns consent_given, consent_date, consent_type, consent_scope,
    and consent_withdrawn_at. Used by the SDK to check current consent status.
    """
    return ConsentResponse(
        consent_given=current_user.consent_given,
        consent_date=current_user.consent_date,
        consent_type=current_user.consent_type,
        consent_scope=(
            json.loads(current_user.consent_scope)
            if current_user.consent_scope
            else None
        ),
        consent_withdrawn_at=current_user.consent_withdrawn_at,
    )


@router.patch(
    "/me/consent",
    response_model=ConsentResponse,
    summary="Update consent tracking",
    description="Update the authenticated student's consent state. "
    "Call this when the user accepts or withdraws consent via the consent banner "
    "or settings. Stores timestamp when consent_given is set to True, and records "
    "consent_withdrawn_at when changed from True to False. "
    "FERPA/COPPA compliance endpoint (Finding B4).",
)
async def patch_my_consent(
    body: ConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's consent tracking state.

    Sets consent_date when consent is first given.
    Sets consent_withdrawn_at when consent is withdrawn.
    """
    now = datetime.now(timezone.utc)

    # If giving consent for the first time, record the date
    if body.consent_given and not current_user.consent_given:
        current_user.consent_date = now
        current_user.consent_withdrawn_at = None

    # If withdrawing consent (was True, now False)
    if not body.consent_given and current_user.consent_given:
        current_user.consent_withdrawn_at = now

    current_user.consent_given = body.consent_given

    if body.consent_type is not None:
        current_user.consent_type = body.consent_type

    if body.consent_scope is not None:
        current_user.consent_scope = json.dumps(body.consent_scope)

    db.add(current_user)
    await db.flush()
    logger.info(
        "Consent updated for user %s: given=%s type=%s scope=%s",
        current_user.id,
        current_user.consent_given,
        current_user.consent_type,
        current_user.consent_scope,
    )

    return ConsentResponse(
        consent_given=current_user.consent_given,
        consent_date=current_user.consent_date,
        consent_type=current_user.consent_type,
        consent_scope=(
            json.loads(current_user.consent_scope)
            if current_user.consent_scope
            else None
        ),
        consent_withdrawn_at=current_user.consent_withdrawn_at,
    )


# ─── Self-Service Data Export (FERPA/COPPA B6) ──────────────────────────


def _format_dt(dt: datetime | None) -> str:
    """Format datetime as ISO string, or empty string."""
    if dt is None:
        return ""
    return dt.isoformat()


@router.get(
    "/me/data",
    response_model=StudentDataResponse,
    summary="Get all my data as JSON",
    description="Return all student records as JSON: profile, sessions, events, "
    "feedback, skill states, enrollments, and consent history. "
    "Self-service FERPA/COPPA compliance endpoint (Finding B6). "
    "No rate limiting is applied — FERPA right of access.",
)
async def get_my_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all student records for the authenticated user as JSON.

    Queries all data categories and returns a structured JSON response.
    Logs the export event for audit trail purposes.
    """
    user_id = current_user.id
    now_str = datetime.now(timezone.utc).isoformat()

    # ── Profile ──
    profile = StudentProfileData(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        display_name=current_user.display_name,
        role=current_user.role,
        created_at=current_user.created_at,
        last_active_at=current_user.last_active_at,
        account_status=current_user.account_status,
        consent_given=current_user.consent_given,
        consent_type=current_user.consent_type,
        consent_date=current_user.consent_date,
        consent_withdrawn_at=current_user.consent_withdrawn_at,
    )

    # ── Sessions ──
    sess_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.student_id == user_id)
        .order_by(SessionModel.started_at.desc())
    )
    sessions = [
        StudentSessionData(
            id=s.id,
            sim_id=s.sim_id,
            page_type=s.page_type,
            started_at=s.started_at,
            ended_at=s.ended_at,
            duration_seconds=s.duration_seconds,
            is_completed=s.is_completed,
        )
        for s in sess_result.scalars().all()
    ]

    # ── Events ──
    event_result = await db.execute(
        select(Event)
        .where(Event.student_id == user_id)
        .order_by(Event.server_ts.desc())
        .limit(5000)
    )
    events = [
        StudentEventData(
            id=e.id,
            session_id=e.session_id,
            event_type=e.event_type,
            event_name=e.event_name,
            event_value=e.event_value,
            client_ts=e.client_ts,
            server_ts=e.server_ts,
        )
        for e in event_result.scalars().all()
    ]

    # ── Feedback ──
    fb_result = await db.execute(
        select(FeedbackLog)
        .where(FeedbackLog.student_id == user_id)
        .order_by(FeedbackLog.created_at.desc())
    )
    feedback = [
        StudentFeedbackData(
            id=f.id,
            session_id=f.session_id,
            sim_id=f.sim_id,
            feedback_type=f.feedback_type,
            feedback_text=f.feedback_text,
            source=f.source,
            was_helpful=f.was_helpful,
            was_dismissed=f.was_dismissed,
            created_at=f.created_at,
        )
        for f in fb_result.scalars().all()
    ]

    # ── Skill States ──
    sk_result = await db.execute(
        select(SkillState)
        .where(SkillState.student_id == user_id)
        .order_by(SkillState.skill_id)
    )
    skill_states = [
        StudentSkillStateData(
            id=s.id,
            skill_id=s.skill_id,
            probability=float(s.probability) if s.probability is not None else 0.0,
            total_attempts=s.total_attempts,
            correct_attempts=s.correct_attempts,
            last_practiced=s.last_practiced,
        )
        for s in sk_result.scalars().all()
    ]

    # ── Enrollments ──
    enr_result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == user_id)
        .order_by(Enrollment.enrolled_at.desc())
    )
    enrollments = [
        StudentEnrollmentData(
            id=e.id,
            class_id=e.class_id,
            enrolled_at=e.enrolled_at,
        )
        for e in enr_result.scalars().all()
    ]

    # ── Audit log ──
    logger.info(
        "DATA_EXPORT [JSON] user=%s sections=%s",
        user_id,
        json.dumps(
            {
                "sessions": len(sessions),
                "events": len(events),
                "feedback": len(feedback),
                "skill_states": len(skill_states),
                "enrollments": len(enrollments),
            }
        ),
    )

    return StudentDataResponse(
        profile=profile,
        sessions=sessions,
        events=events,
        feedback=feedback,
        skill_states=skill_states,
        enrollments=enrollments,
        exported_at=now_str,
    )


@router.get(
    "/me/export",
    summary="Download all my data as CSV",
    description="Download a CSV file containing all student records: "
    "profile, sessions, events, feedback, skill states, "
    "enrollments, and consent history. "
    "Self-service FERPA/COPPA compliance endpoint (Finding B6). "
    "No rate limiting is applied — FERPA right of access.",
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "CSV file with all student data",
        },
    },
)
async def export_my_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download all student records as CSV.

    Produces a CSV with a 'section' column identifying each row's data
    category. Sections: profile, session, event, feedback, skill_state,
    enrollment. Each section has its own field layout.
    """
    user_id = current_user.id
    now_str = datetime.now(timezone.utc).isoformat()

    rows: list[dict] = []

    # ── Profile row ──
    rows.append(
        {
            "section": "profile",
            "field1": current_user.id or "",
            "field2": current_user.email or "",
            "field3": current_user.username or "",
            "field4": current_user.display_name or "",
            "field5": current_user.role or "",
            "field6": current_user.account_status,
            "field7": f"consent={current_user.consent_given} type={current_user.consent_type or ''}",
            "field8": f"created={_format_dt(current_user.created_at)}",
            "exported_at": now_str,
        }
    )

    # ── Session rows ──
    sess_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.student_id == user_id)
        .order_by(SessionModel.started_at.desc())
    )
    for s in sess_result.scalars().all():
        rows.append(
            {
                "section": "session",
                "field1": s.id or "",
                "field2": s.sim_id or "",
                "field3": s.page_type,
                "field4": _format_dt(s.started_at),
                "field5": _format_dt(s.ended_at),
                "field6": str(s.duration_seconds or ""),
                "field7": "completed" if s.is_completed else "incomplete",
                "field8": "",
                "exported_at": now_str,
            }
        )

    # ── Event rows ──
    event_result = await db.execute(
        select(Event)
        .where(Event.student_id == user_id)
        .order_by(Event.server_ts.desc())
        .limit(5000)
    )
    for e in event_result.scalars().all():
        rows.append(
            {
                "section": "event",
                "field1": str(e.id),
                "field2": e.session_id,
                "field3": e.event_type,
                "field4": e.event_name or "",
                "field5": json.dumps(e.event_value) if e.event_value else "",
                "field6": _format_dt(e.client_ts),
                "field7": _format_dt(e.server_ts),
                "field8": "",
                "exported_at": now_str,
            }
        )

    # ── Feedback rows ──
    fb_result = await db.execute(
        select(FeedbackLog)
        .where(FeedbackLog.student_id == user_id)
        .order_by(FeedbackLog.created_at.desc())
    )
    for f in fb_result.scalars().all():
        rows.append(
            {
                "section": "feedback",
                "field1": f.id,
                "field2": f.session_id,
                "field3": f.feedback_type,
                "field4": f.feedback_text[:500] if f.feedback_text else "",  # truncate long text
                "field5": f.source,
                "field6": f"helpful={f.was_helpful} dismissed={f.was_dismissed}",
                "field7": _format_dt(f.created_at),
                "field8": "",
                "exported_at": now_str,
            }
        )

    # ── Skill state rows ──
    sk_result = await db.execute(
        select(SkillState)
        .where(SkillState.student_id == user_id)
        .order_by(SkillState.skill_id)
    )
    for s in sk_result.scalars().all():
        rows.append(
            {
                "section": "skill_state",
                "field1": s.skill_id,
                "field2": str(float(s.probability)) if s.probability is not None else "",
                "field3": str(s.total_attempts),
                "field4": str(s.correct_attempts),
                "field5": _format_dt(s.last_practiced),
                "field6": "",
                "field7": "",
                "field8": "",
                "exported_at": now_str,
            }
        )

    # ── Enrollment rows ──
    enr_result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == user_id)
        .order_by(Enrollment.enrolled_at.desc())
    )
    for e in enr_result.scalars().all():
        rows.append(
            {
                "section": "enrollment",
                "field1": e.id,
                "field2": e.class_id,
                "field3": _format_dt(e.enrolled_at),
                "field4": "",
                "field5": "",
                "field6": "",
                "field7": "",
                "field8": "",
                "exported_at": now_str,
            }
        )

    # ── Build CSV ──
    output = io.StringIO()
    fieldnames = [
        "section",
        "field1",
        "field2",
        "field3",
        "field4",
        "field5",
        "field6",
        "field7",
        "field8",
        "exported_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    # ── Audit log ──
    logger.info(
        "DATA_EXPORT [CSV] user=%s total_rows=%s",
        user_id,
        len(rows),
    )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="my_data_{user_id[:8]}.csv"'
        },
    )


# ─── Generate Parent Verification Token (FERPA/COPPA B2) ─────────────────


@router.post(
    "/{id}/generate-parent-token",
    response_model=GenerateParentTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a parent verification token",
    description="Generate a token that a parent/guardian can use to access "
    "the student's educational records via the parent data access endpoint. "
    "Requires authentication as the student themselves or an authorized teacher. "
    "FERPA/COPPA compliance endpoint (Finding B2).",
)
async def student_generate_parent_token(
    id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a parent verification token for the student.

    The token allows a parent/guardian to view the student's educational
    records via GET /api/v1/parent/{child_id}/data?token=<token>.
    Only the student themselves or an authorized teacher/admin can generate
    this token.

    If a token already exists, it is returned unchanged (idempotent).
    """
    # Authorization: self, teacher of the student, or admin
    if current_user.id != id:
        if current_user.role == "teacher":
            # Check if student is in one of this teacher's classes
            result = await db.execute(
                select(Enrollment)
                .join(ClassModel, ClassModel.id == Enrollment.class_id)
                .where(
                    ClassModel.teacher_id == current_user.id,
                    Enrollment.student_id == id,
                )
                .limit(1)
            )
            if result.scalar_one_or_none() is None and current_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to generate a token for this student",
                )
        elif current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only generate a token for your own account",
            )

    # Find the student
    result = await db.execute(select(User).where(User.id == id))
    student = result.scalar_one_or_none()

    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found",
        )

    if student.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has been deactivated",
        )

    # Generate token if one doesn't already exist (idempotent)
    from uuid import uuid4

    if not student.parent_verification_token:
        student.parent_verification_token = str(uuid4())
        db.add(student)
        await db.flush()
        logger.info(
            "Parent verification token generated for student %s by %s",
            id,
            current_user.id,
        )

    return GenerateParentTokenResponse(
        parent_verification_token=student.parent_verification_token,
    )
