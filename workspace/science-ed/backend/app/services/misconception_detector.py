"""Misconception detection service — analyses student event patterns
to identify specific science misconceptions from event sequences.

Pattern types:
- repeated_error: Same wrong answer submitted N+ times on the same concept.
- oscillating: Student alternates between two specific wrong answers.
- rapid_guessing: Many rapid-fire incorrect submissions.
- sign_error: Consistent sign/direction mistakes (e.g. always sets velocity
  positive when negative is correct).

Each NGSS-aligned simulation has its own set of misconception patterns
defined in MISCONCEPTION_PATTERNS by sim_slug.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────


@dataclass
class MisconceptionPattern:
    """A pattern definition that maps event observations to a misconception."""

    concept: str
    """Short label like 'velocity-vs-acceleration'."""

    ngss_id: str
    """NGSS standard identifier."""

    pattern_type: str
    """One of: repeated_error, oscillating, rapid_guessing, sign_error."""

    event_types: list[str]
    """Which event_type values to filter (e.g. ['sim_interaction'])."""

    event_names: list[str] | None = None
    """Optional filter on event_name (e.g. ['answer_submit']). None = any."""

    target_field: str | None = None
    """The nested field in event_value to analyse (dot-notation supported)."""

    incorrect_values: list[Any] | None = None
    """Values considered incorrect for repeated_error / sign_error patterns."""

    min_count: int = 3
    """Minimum evidence events needed to trigger."""

    window_count: int = 15
    """Analyse this many most-recent events."""

    confidence_weight: float = 0.6
    """Base confidence contributed by this pattern."""

    description: str = ""
    """Human-readable description of what the misconception looks like."""


@dataclass
class DetectionResult:
    """A single triggered detection with supporting evidence."""

    concept: str
    ngss_id: str
    sim_slug: str
    pattern_type: str
    confidence: float
    evidence_events: list[dict]
    count: int
    description: str


# ──────────────────────────────────────────────────────────────────────
# Misconception pattern registry — one entry per sim
# ──────────────────────────────────────────────────────────────────────

# Each key is a sim_slug; each value is a list of patterns to check.

MISCONCEPTION_PATTERNS: dict[str, list[MisconceptionPattern]] = {
    "projectile-motion-simulation": [
        MisconceptionPattern(
            concept="velocity-vs-acceleration",
            ngss_id="HS-PS2-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.initial_velocity_y",
            incorrect_values=[0],
            min_count=3,
            confidence_weight=0.7,
            description="Student appears to confuse velocity with acceleration — "
            "consistently sets initial vertical velocity to 0 "
            "instead of 9.8 m/s (gravity acceleration).",
        ),
        MisconceptionPattern(
            concept="horizontal-velocity-changes",
            ngss_id="HS-PS2-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.retaining_horizontal_velocity",
            incorrect_values=[False],
            min_count=3,
            confidence_weight=0.65,
            description="Student believes horizontal velocity changes during "
            "projectile motion — may think a force acts horizontally.",
        ),
        MisconceptionPattern(
            concept="heavier-falls-faster",
            ngss_id="HS-PS2-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.drop_time",
            incorrect_values=["mass_dependent"],
            min_count=2,
            confidence_weight=0.8,
            description="Student thinks heavier objects fall faster — "
            "does not understand that gravity accelerates all masses equally.",
        ),
        MisconceptionPattern(
            concept="launch-angle-speed-tradeoff",
            ngss_id="HS-PS2-1",
            pattern_type="oscillating",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.best_angle_selection",
            incorrect_values=[15, 75],  # extremes instead of ~45°
            min_count=3,
            confidence_weight=0.55,
            description="Student oscillates between extreme launch angles "
            "(15° and 75°) — may not understand the 45° optimum for range.",
        ),
    ],
    "conservation-of-momentum-simulation": [
        MisconceptionPattern(
            concept="momentum-force-confusion",
            ngss_id="HS-PS2-2",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.momentum_vs_force",
            incorrect_values=["force"],
            min_count=3,
            confidence_weight=0.7,
            description="Student confuses momentum with force — "
            "may answer momentum-related questions using force concepts.",
        ),
        MisconceptionPattern(
            concept="mass-determines-force",
            ngss_id="HS-PS2-2",
            pattern_type="sign_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.collision_force_ratio",
            incorrect_values=["heavier_always_exerts_more"],
            min_count=2,
            confidence_weight=0.75,
            description="Student believes the heavier object always exerts "
            "more force in a collision (Newton's 3rd law misconception).",
        ),
        MisconceptionPattern(
            concept="elastic-vs-inelastic",
            ngss_id="HS-PS2-2",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.energy_conservation_type",
            incorrect_values=["always_elastic"],
            min_count=3,
            confidence_weight=0.65,
            description="Student thinks kinetic energy is conserved in all "
            "collisions — confuses elastic with inelastic collisions.",
        ),
        MisconceptionPattern(
            concept="rapid-guessing-momentum",
            ngss_id="HS-PS2-2",
            pattern_type="rapid_guessing",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.guess_indicator",
            incorrect_values=[True],
            min_count=4,
            confidence_weight=0.5,
            description="Student is rapidly guessing through momentum "
            "questions — shows lack of conceptual understanding.",
        ),
    ],
    "wave-superposition-3-d": [
        MisconceptionPattern(
            concept="amplitude-frequency-confusion",
            ngss_id="HS-PS4-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.wave_property",
            incorrect_values=["amplitude_is_frequency"],
            min_count=3,
            confidence_weight=0.7,
            description="Student confuses amplitude with frequency — "
            "may think higher amplitude means higher frequency.",
        ),
        MisconceptionPattern(
            concept="wave-requires-medium",
            ngss_id="HS-PS4-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.medium_required",
            incorrect_values=[True],
            min_count=2,
            confidence_weight=0.8,
            description="Student believes all waves require a medium — "
            "does not understand electromagnetic waves can travel through vacuum.",
        ),
        MisconceptionPattern(
            concept="wavelength-frequency-inverse",
            ngss_id="HS-PS4-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.wavelength_frequency_relationship",
            incorrect_values=["direct"],
            min_count=3,
            confidence_weight=0.7,
            description="Student thinks wavelength and frequency have a "
            "direct (not inverse) relationship.",
        ),
        MisconceptionPattern(
            concept="constructive-destructive-interference",
            ngss_id="HS-PS4-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.interference_type",
            incorrect_values=["same_phase_destructive"],
            min_count=3,
            confidence_weight=0.6,
            description="Student confuses constructive and destructive "
            "interference — thinks same-phase waves cancel out.",
        ),
    ],
    "chemical-reactions-outcomes": [
        MisconceptionPattern(
            concept="atoms-created-destroyed",
            ngss_id="HS-PS1-2",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.conservation_matter",
            incorrect_values=["created_or_destroyed"],
            min_count=3,
            confidence_weight=0.8,
            description="Student believes atoms can be created or destroyed "
            "during a chemical reaction — does not understand conservation of matter.",
        ),
        MisconceptionPattern(
            concept="reactants-products-confusion",
            ngss_id="HS-PS1-2",
            pattern_type="oscillating",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.identify_reactants",
            incorrect_values=[False],  # keeps switching each time
            min_count=3,
            confidence_weight=0.55,
            description="Student alternates between identifying reactants "
            "and products correctly — inconsistent understanding.",
        ),
        MisconceptionPattern(
            concept="coefficients-change-substance",
            ngss_id="HS-PS1-2",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.coefficient_meaning",
            incorrect_values=["changes_substance"],
            min_count=3,
            confidence_weight=0.7,
            description="Student thinks coefficients in a balanced equation "
            "change the substance itself rather than the number of molecules.",
        ),
    ],
    "interactive-boat-river-crossing-simulation": [
        MisconceptionPattern(
            concept="net-force-direction",
            ngss_id="HS-PS2-1",
            pattern_type="sign_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.net_force_direction",
            incorrect_values=["opposite"],
            min_count=3,
            confidence_weight=0.65,
            description="Student consistently identifies net force in the "
            "wrong direction — may be confusing individual forces with net force.",
        ),
        MisconceptionPattern(
            concept="constant-speed-no-force",
            ngss_id="HS-PS2-1",
            pattern_type="repeated_error",
            event_types=["sim_interaction"],
            event_names=["answer_submit"],
            target_field="value.constant_velocity_force",
            incorrect_values=["no_force_needed"],
            min_count=3,
            confidence_weight=0.7,
            description="Student thinks constant velocity requires zero net "
            "force — does not understand balanced forces produce constant velocity.",
        ),
    ],
}


def _get_nested_value(event_value: dict | None, field_path: str | None) -> Any:
    """Resolve a dot-notation path in a nested dict.

    If field_path is None, returns the entire event_value dict.

    >>> _get_nested_value({'value': {'key': 42}}, 'value.key')
    42
    >>> _get_nested_value({'key': 42}, None)
    {'key': 42}
    """
    if field_path is None:
        return event_value
    if not event_value:
        return None
    parts = field_path.split(".")
    current: Any = event_value
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


# ──────────────────────────────────────────────────────────────────────
# Pattern matchers (pure, stateless functions for testability)
# ──────────────────────────────────────────────────────────────────────


def _detect_repeated_error(
    recent: list[dict],
    pattern: MisconceptionPattern,
) -> DetectionResult | None:
    """Detect N+ incorrect answers on the same field."""
    incorrect_count = 0
    evidence: list[dict] = []

    for evt in recent:
        val = _get_nested_value(evt.get("event_value", {}), pattern.target_field)
        if val is not None and (
            pattern.incorrect_values is None or val in pattern.incorrect_values
        ):
            incorrect_count += 1
            evidence.append(evt)

    if incorrect_count >= pattern.min_count:
        confidence = min(
            pattern.confidence_weight + (incorrect_count - pattern.min_count) * 0.05,
            0.99,
        )
        return DetectionResult(
            concept=pattern.concept,
            ngss_id=pattern.ngss_id,
            sim_slug="",  # filled by caller
            pattern_type=pattern.pattern_type,
            confidence=round(confidence, 2),
            evidence_events=evidence,
            count=incorrect_count,
            description=pattern.description,
        )
    return None


def _detect_oscillating(
    recent: list[dict],
    pattern: MisconceptionPattern,
) -> DetectionResult | None:
    """Detect oscillation between two or more wrong answers.

    True oscillation means the student is switching between at least two
    distinct values from the incorrect_values set, with at least one
    transition (value-a → value-b) in the sequence.
    """
    vals: list[Any] = []
    for evt in recent:
        v = _get_nested_value(evt.get("event_value", {}), pattern.target_field)
        if v is not None:
            vals.append(v)

    if len(vals) < pattern.min_count:
        return None

    if not pattern.incorrect_values or len(pattern.incorrect_values) < 2:
        return None

    targets = set(pattern.incorrect_values)
    # Filter to only values in the target set
    sub: list[Any] = [v for v in vals if v in targets]

    if len(sub) < pattern.min_count:
        return None

    # Check for actual alternation: at least two different values
    # appear AND there's at least one transition between them.
    unique_vals = set(sub)
    if len(unique_vals) < 2:
        return None

    # Count transitions: adjacent pairs where value changes
    transitions = sum(
        1 for i in range(len(sub) - 1) if sub[i] != sub[i + 1]
    )
    if transitions == 0:
        return None

    evidence: list[dict] = [
        evt
        for evt in recent
        if _get_nested_value(evt.get("event_value", {}), pattern.target_field)
        in targets
    ]
    confidence = min(
        pattern.confidence_weight + min(transitions, 5) * 0.04,
        0.95,
    )
    return DetectionResult(
        concept=pattern.concept,
        ngss_id=pattern.ngss_id,
        sim_slug="",
        pattern_type=pattern.pattern_type,
        confidence=round(confidence, 2),
        evidence_events=evidence,
        count=len(sub),
        description=pattern.description,
    )


def _detect_rapid_guessing(
    recent: list[dict],
    pattern: MisconceptionPattern,
) -> DetectionResult | None:
    """Detect rapid-fire guessing — many submissions in short time with low info."""
    guess_count = 0
    evidence: list[dict] = []

    for evt in recent:
        val = _get_nested_value(evt.get("event_value", {}), pattern.target_field)
        if val is not None and val in (pattern.incorrect_values or [True]):
            guess_count += 1
            evidence.append(evt)

    if guess_count >= pattern.min_count:
        confidence = min(
            pattern.confidence_weight + (guess_count - pattern.min_count) * 0.04,
            0.90,
        )
        return DetectionResult(
            concept=pattern.concept,
            ngss_id=pattern.ngss_id,
            sim_slug="",
            pattern_type=pattern.pattern_type,
            confidence=round(confidence, 2),
            evidence_events=evidence,
            count=guess_count,
            description=pattern.description,
        )
    return None


def _detect_sign_error(
    recent: list[dict],
    pattern: MisconceptionPattern,
) -> DetectionResult | None:
    """Detect consistent sign/direction errors."""
    direction_count = 0
    evidence: list[dict] = []

    for evt in recent:
        val = _get_nested_value(evt.get("event_value", {}), pattern.target_field)
        if val is not None and val in (pattern.incorrect_values or []):
            direction_count += 1
            evidence.append(evt)

    if direction_count >= pattern.min_count:
        confidence = min(
            pattern.confidence_weight + (direction_count - pattern.min_count) * 0.06,
            0.95,
        )
        return DetectionResult(
            concept=pattern.concept,
            ngss_id=pattern.ngss_id,
            sim_slug="",
            pattern_type=pattern.pattern_type,
            confidence=round(confidence, 2),
            evidence_events=evidence,
            count=direction_count,
            description=pattern.description,
        )
    return None


# Map pattern_type to its detector function
_DETECTOR_MAP = {
    "repeated_error": _detect_repeated_error,
    "oscillating": _detect_oscillating,
    "rapid_guessing": _detect_rapid_guessing,
    "sign_error": _detect_sign_error,
}


# ──────────────────────────────────────────────────────────────────────
# Public API: run detection for a student across all sims
# ──────────────────────────────────────────────────────────────────────


async def detect_misconceptions(
    student_id: str,
    db: AsyncSession,
    *,
    sim_slug: str | None = None,
    max_events_per_sim: int = 50,
) -> list[DetectionResult]:
    """Analyse a student's event history and return detected misconceptions.

    Args:
        student_id: The student's UUID string.
        db: Async SQLAlchemy session.
        sim_slug: If provided, only analyse this sim. Otherwise all sims
            with registered patterns are checked.
        max_events_per_sim: Cap on events to fetch per simulation.

    Returns:
        List of DetectionResult objects (one per triggered pattern).
    """
    sims_to_check = (
        [sim_slug] if sim_slug else list(MISCONCEPTION_PATTERNS.keys())
    )
    all_results: list[DetectionResult] = []

    for sim in sims_to_check:
        patterns = MISCONCEPTION_PATTERNS.get(sim)
        if not patterns:
            logger.debug("No misconception patterns registered for sim '%s'", sim)
            continue

        # Fetch recent events for this student + sim
        events = await _fetch_events_for_sim(student_id, sim, db, max_events_per_sim)
        if not events:
            logger.debug(
                "No events found for student '%s' + sim '%s'", student_id, sim
            )
            continue

        # Convert ORM rows to plain dicts
        event_dicts = [
            {
                "event_type": e.event_type,
                "event_name": e.event_name,
                "event_value": e.event_value or {},
                "client_ts": e.client_ts,
            }
            for e in events
        ]

        # Filter to relevant event types/names for this sim's patterns
        for pattern in patterns:
            matched = _filter_events(event_dicts, pattern)
            detector = _DETECTOR_MAP.get(pattern.pattern_type)
            if detector is None:
                continue

            result = detector(matched, pattern)
            if result is not None:
                result.sim_slug = sim
                all_results.append(result)

    return all_results


def _filter_events(
    events: list[dict], pattern: MisconceptionPattern
) -> list[dict]:
    """Filter events to only those matching the pattern's event_type/name."""
    filtered = []
    for evt in events:
        if evt.get("event_type") not in pattern.event_types:
            continue
        if pattern.event_names and evt.get("event_name") not in pattern.event_names:
            continue
        filtered.append(evt)
    return filtered


async def _fetch_events_for_sim(
    student_id: str,
    sim_slug: str,
    db: AsyncSession,
    limit: int = 50,
) -> list[Event]:
    """Query most recent events for a student+sim combination."""
    from sqlalchemy import and_

    # Join through SessionModel → sim.slug
    from app.models import SessionModel

    stmt = (
        select(Event)
        .join(SessionModel, Event.session_id == SessionModel.id)
        .where(
            and_(
                Event.student_id == student_id,
                SessionModel.sim_id == sim_slug,
            )
        )
        .order_by(Event.server_ts.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
