"""
Bayesian Knowledge Tracing (BKT) Service — core math and database operations.

Implements the standard 4-parameter BKT model (Corbett & Anderson, 1995):

    Parameters:
        P(K₀)  — prior knowledge probability (probability)
        P(T)   — learning/transition rate (learning_rate)
        P(G)   — guess rate (guess_rate)
        P(S)   — slip rate (slip_rate)

    Update equations (Bayes' Theorem + learning transition):

        If correct:
            P(K|obs) = P(K) * (1 - P(S)) / (P(K) * (1 - P(S)) + (1 - P(K)) * P(G))
        If incorrect:
            P(K|obs) = P(K) * P(S) / (P(K) * P(S) + (1 - P(K)) * (1 - P(G)))

        P(K_next) = P(K|obs) + (1 - P(K|obs)) * P(T)

All update functions are pure / stateless — no side-effects.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_state import SkillState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_P_KNOWN: float = 0.10
DEFAULT_P_LEARN: float = 0.30
DEFAULT_P_GUESS: float = 0.20
DEFAULT_P_SLIP: float = 0.10

MASTERY_THRESHOLD: float = 0.90
PREREQ_THRESHOLD: float = 0.70

# ---------------------------------------------------------------------------
# Pure BKT math — stateless, testable without DB
# ---------------------------------------------------------------------------


def bkt_update(
    p_known: float,
    p_learn: float,
    p_guess: float,
    p_slip: float,
    is_correct: bool,
) -> float:
    """Single-step BKT update: compute posterior P(K) after one observation.

    Parameters
    ----------
    p_known : float — prior probability student knows the skill [0, 1]
    p_learn : float — probability of learning per opportunity (P(T)) [0, 1]
    p_guess : float — probability of correct answer when student doesn't know (P(G)) [0, 1]
    p_slip : float — probability of wrong answer when student does know (P(S)) [0, 1]
    is_correct : bool — whether the student answered correctly

    Returns
    -------
    float — posterior P(K) in [0, 1]
    """
    if is_correct:
        numerator = p_known * (1.0 - p_slip)
        denominator = numerator + (1.0 - p_known) * p_guess
    else:
        numerator = p_known * p_slip
        denominator = numerator + (1.0 - p_known) * (1.0 - p_guess)

    p_k_given_obs = numerator / denominator if denominator > 0.0 else 0.0

    # Apply learning probability (student may learn even after wrong answer)
    p_k_after = p_k_given_obs + (1.0 - p_k_given_obs) * p_learn

    return max(0.0, min(1.0, p_k_after))


def compute_mastery_level(p_known: float) -> str:
    """Classify P(K) into a human-readable tier.

    Returns one of: 'struggling', 'introductory', 'developing', 'proficient', 'mastered'.
    """
    if p_known < 0.15:
        return "struggling"
    elif p_known < 0.35:
        return "introductory"
    elif p_known < 0.70:
        return "developing"
    elif p_known < 0.90:
        return "proficient"
    else:
        return "mastered"


def apply_forgetting_curve(
    p_known: float,
    days_since_practice: float,
    decay_rate: float = 0.02,
    floor: float = 0.5,
) -> float:
    """Apply exponential forgetting decay after a gap in practice.

    Parameters
    ----------
    p_known : float — current P(K)
    days_since_practice : float — days since last practice for this skill
    decay_rate : float — exponential decay factor (default 0.02)
    floor : float — minimum P(K) after decay (default 0.5, never below 50%)

    Returns
    -------
    float — decayed P(K)
    """
    if days_since_practice <= 7.0:
        return p_known
    decay_factor = math.exp(-decay_rate * days_since_practice)
    return p_known * max(decay_factor, floor)


# ---------------------------------------------------------------------------
# DB access functions
# ---------------------------------------------------------------------------


async def get_skill_states(
    db: AsyncSession,
    student_id: str,
) -> list[SkillState]:
    """Fetch all SkillState records for a student."""
    result = await db.execute(
        select(SkillState).where(SkillState.student_id == student_id)
    )
    return list(result.scalars().all())


async def get_skill_state(
    db: AsyncSession,
    student_id: str,
    skill_id: str,
) -> SkillState | None:
    """Fetch a single SkillState record for a student+skill pair."""
    result = await db.execute(
        select(SkillState).where(
            SkillState.student_id == student_id,
            SkillState.skill_id == skill_id,
        )
    )
    return result.scalar_one_or_none()


async def update_skill_state(
    db: AsyncSession,
    student_id: str,
    skill_id: str,
    is_correct: bool,
) -> float:
    """Fetch current P(K) for a student+skill, run BKT update, persist, return new P(K).

    Creates a SkillState row with default parameters if none exists yet
    (lazy cold-start within update).
    """
    state = await get_skill_state(db, student_id, skill_id)
    if state is None:
        state = SkillState(
            student_id=student_id,
            skill_id=skill_id,
            probability=DEFAULT_P_KNOWN,
            learning_rate=DEFAULT_P_LEARN,
            guess_rate=DEFAULT_P_GUESS,
            slip_rate=DEFAULT_P_SLIP,
        )
        db.add(state)

    new_p_known = bkt_update(
        p_known=float(state.probability),
        p_learn=float(state.learning_rate),
        p_guess=float(state.guess_rate),
        p_slip=float(state.slip_rate),
        is_correct=is_correct,
    )

    state.probability = new_p_known
    state.total_attempts = (state.total_attempts or 0) + 1
    if is_correct:
        state.correct_attempts = (state.correct_attempts or 0) + 1
    state.last_practiced = datetime.now(timezone.utc)

    await db.flush()
    return new_p_known


async def get_mastery_vector(
    db: AsyncSession,
    student_id: str,
) -> dict[str, float]:
    """Return current mastery probabilities across all skills.

    For skills the student hasn't practiced yet, returns the default prior (0.10).
    Applies forgetting-curve decay for skills with last_practice > 7 days ago.
    """
    states = await get_skill_states(db, student_id)
    now = datetime.now(timezone.utc)

    mastery: dict[str, float] = {s.skill_id: float(s.probability) for s in states}

    # Apply forgetting decay
    for state in states:
        if state.last_practiced is not None:
            last_practiced = state.last_practiced
            # SQLite may return naive datetimes from TIMESTAMP(timezone=True)
            if last_practiced.tzinfo is None:
                last_practiced = last_practiced.replace(tzinfo=timezone.utc)
            days = (now - last_practiced).total_seconds() / 86400.0
            mastery[state.skill_id] = apply_forgetting_curve(
                mastery[state.skill_id], days
            )

    return mastery
