"""
Pydantic validators for extra_data JSON columns (compliance Finding 1.4).

Each model with an ``extra_data`` JSON column must define the set of
allowed keys and a validator that rejects unknown keys.  This module
provides:

* Allowed-key frozensets for every model that has ``extra_data``
* ``AfterValidator`` type aliases for use in Pydantic schemas (API layer)
* ``validate_extra_data_dict()`` for service-layer code that constructs
  ``extra_data`` dicts directly.

Usage (API schema)::

    from app.schemas.extra_data import EventExtraData

    class EventCreate(BaseModel):
        event_type: str
        extra_data: EventExtraData = Field(default_factory=dict)

Usage (service layer)::

    from app.schemas.extra_data import (
        ALLOWED_TEACHER_ACTION_KEYS,
        validate_extra_data_dict,
    )

    extra_data = validate_extra_data_dict(
        {"sim_slug": "ph-scale", "required": True},
        ALLOWED_TEACHER_ACTION_KEYS,
        field_name="TeacherAction.extra_data",
    )
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator


# ──────────────────────────────────────────────
# Allowed key sets — one frozenset per model
# ──────────────────────────────────────────────

# Event.extra_data — simulation state snapshot for session replay
ALLOWED_EVENT_KEYS: frozenset[str] = frozenset({"sim_state"})

# SessionModel.extra_data — reserved; no keys consumed yet
ALLOWED_SESSION_KEYS: frozenset[str] = frozenset()

# User.extra_data — reserved; no keys consumed yet
ALLOWED_USER_KEYS: frozenset[str] = frozenset()

# TeacherAction.extra_data — assignment metadata
ALLOWED_TEACHER_ACTION_KEYS: frozenset[str] = frozenset(
    {"sim_slug", "sim_title", "required", "due_date"}
)

# Sim.extra_data — dynamic keys (NGSS codes) with nested {ngss_url: str} values.
# Because the keys are dynamic (any NGSS standard code) we cannot enumerate them,
# but we validate that each *value* is a dict with exactly one expected key.
ALLOWED_SIM_KEYS: frozenset[str] = frozenset()  # dynamic keys — see _validate_sim_extra_data


# ──────────────────────────────────────────────
# Validator implementations
# ──────────────────────────────────────────────


def _validate_keys(
    value: dict[str, Any],
    allowed: frozenset[str],
    field_name: str = "extra_data",
) -> dict[str, Any]:
    """Reject any key in *value* that is not in *allowed*.

    An empty *allowed* set means *no* keys are permitted (reserved).
    Raises ``ValueError`` with a clear message listing the unknown keys.
    """
    unknown = set(value.keys()) - allowed
    if unknown:
        raise ValueError(
            f"Unknown {field_name} keys: {', '.join(sorted(unknown))}. "
            f"Allowed keys: {', '.join(sorted(allowed)) or '<none (reserved)>'}"
        )
    return value


def _validate_sim_extra_data(value: dict[str, Any]) -> dict[str, Any]:
    """Validate Sim.extra_data which has dynamic NGSS-code keys.

    Each key must look like an NGSS code (e.g. ``HS-PS1-1``) and each
    value must be a dict with a single ``ngss_url`` key.
    """
    import re  # keep import local so module loads without deps

    ngss_pattern = re.compile(r"^(HS|MS)\-[A-Z]{2,4}\d*\-?\d*$")
    for key, val in value.items():
        if not ngss_pattern.match(key):
            raise ValueError(
                f"Invalid key in Sim.extra_data: {key!r}. "
                "Dynamic keys must be NGSS standard codes (e.g. HS-PS1-1)."
            )
        if not isinstance(val, dict) or list(val.keys()) != ["ngss_url"]:
            raise ValueError(
                f"Invalid value for Sim.extra_data key {key!r}. "
                "Expected {{'ngss_url': str}}."
            )
        if not isinstance(val.get("ngss_url"), str):
            raise ValueError(
                f"Invalid ngss_url for Sim.extra_data key {key!r}. "
                "Expected a string."
            )
    return value


# ──────────────────────────────────────────────
# Pydantic AfterValidator type aliases
# ──────────────────────────────────────────────

EventExtraData = Annotated[
    dict[str, Any],
    AfterValidator(lambda v: _validate_keys(v, ALLOWED_EVENT_KEYS, "Event.extra_data")),
]

SessionExtraData = Annotated[
    dict[str, Any],
    AfterValidator(lambda v: _validate_keys(v, ALLOWED_SESSION_KEYS, "SessionModel.extra_data")),
]

UserExtraData = Annotated[
    dict[str, Any],
    AfterValidator(lambda v: _validate_keys(v, ALLOWED_USER_KEYS, "User.extra_data")),
]

TeacherActionExtraData = Annotated[
    dict[str, Any],
    AfterValidator(
        lambda v: _validate_keys(v, ALLOWED_TEACHER_ACTION_KEYS, "TeacherAction.extra_data")
    ),
]

SimExtraData = Annotated[
    dict[str, Any],
    AfterValidator(_validate_sim_extra_data),
]


# ──────────────────────────────────────────────
# Service-layer helper
# ──────────────────────────────────────────────


def validate_extra_data_dict(
    value: dict[str, Any],
    allowed_keys: frozenset[str],
    field_name: str = "extra_data",
) -> dict[str, Any]:
    """Validate an ``extra_data`` dict at the service layer.

    This is a standalone function (not a Pydantic validator) so service
    code that constructs ``extra_data`` dicts directly can call it.

    Raises ``ValueError`` on unknown keys.

    Example::

        from app.schemas.extra_data import (
            ALLOWED_TEACHER_ACTION_KEYS,
            validate_extra_data_dict,
        )

        extra_data = validate_extra_data_dict(
            {"sim_slug": "ph-scale", "required": True},
            ALLOWED_TEACHER_ACTION_KEYS,
            field_name="TeacherAction.extra_data",
        )
    """
    return _validate_keys(value, allowed_keys, field_name)
