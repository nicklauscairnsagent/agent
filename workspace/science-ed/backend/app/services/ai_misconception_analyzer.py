"""AI/LLM-powered misconception analysis — enriches pattern-based detection with
nuanced LLM reasoning about student misconceptions, teaching guidance, and
remediation recommendations.

Architecture:
1. Takes pattern-based DetectionResult[] as input.
2. Fetches raw event stream for the student+sim to provide rich context.
3. Builds an LLM prompt with educational context from misconception_context.py.
4. Parses the structured LLM response into AIMisconceptionResult objects.
5. Handles edge cases: LLM failure → silent fallback, insufficient data → skip.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.data.misconception_context import SIM_MISCONCEPTION_CONTEXT

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────


@dataclass
class AIMisconceptionResult:
    """A single AI-detected misconception with teaching context."""

    concept: str
    """Short educational concept label (e.g. 'velocity-vs-acceleration')."""

    specific_misconception: str
    """Natural-language description of the specific misconception detected."""

    confidence: float
    """Confidence score 0.0–1.0. Only results > 0.6 are surfaced to teachers."""

    explanation: str
    """Detailed explanation of why this behavior indicates the misconception."""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AIAnalysisOutput:
    """Full output from the AI misconception analyzer."""

    detected_misconceptions: list[AIMisconceptionResult] = field(default_factory=list)
    """List of AI-detected misconceptions (may be empty)."""

    teaching_guidance: str | None = None
    """1-2 sentences on how to address this misconception."""

    recommended_remediation: str | None = None
    """Suggestion for which sim or activity to assign next."""

    ai_used: bool = False
    """Whether the AI analyzer was invoked."""

    ai_error: str | None = None
    """Error message if AI call failed (for diagnostic logging)."""

    def to_dict(self) -> dict:
        return {
            "detected_misconceptions": [m.to_dict() for m in self.detected_misconceptions],
            "teaching_guidance": self.teaching_guidance,
            "recommended_remediation": self.recommended_remediation,
            "ai_used": self.ai_used,
            "ai_error": self.ai_error,
        }


# ──────────────────────────────────────────────────────────────────────
# LLM prompt construction
# ──────────────────────────────────────────────────────────────────────

_MIN_EVENTS_FOR_AI = 3
"""Minimum number of answer events required to run AI analysis."""

_AI_SYSTEM_PROMPT = """You are an expert science education diagnostician with deep knowledge of high school physics and chemistry misconceptions aligned to the NGSS (Next Generation Science Standards).

Your task is to analyze a student's interaction pattern with a science simulation and identify possible misconceptions.

You will receive:
1. The simulation's educational context (concept being taught, known misconceptions, typical wrong answers)
2. The pattern-based detector's findings (if any)
3. The student's recent answer sequence (right/wrong + specific answers)

Analyze carefully and return your response as valid JSON only — no markdown, no extra text.

Return a JSON object with this structure:
{
  "detected_misconceptions": [
    {
      "concept": "short-label-e-g-velocity-vs-acceleration",
      "specific_misconception": "natural language description of what the student misunderstands",
      "confidence": 0.0-1.0,
      "explanation": "detailed explanation connecting the student's answers to this misconception"
    }
  ],
  "teaching_guidance": "1-2 actionable sentences for the teacher on how to address this",
  "recommended_remediation": "suggested next sim or activity for the student"
}

Guidelines:
- Confidence should reflect severity and certainty of the misconception.
- Only return misconceptions with confidence > 0.4 (lower ones are too speculative).
- If the student shows no clear misconceptions, return an empty detected_misconceptions list.
- Sort misconceptions by confidence descending.
- Teaching guidance must be actionable and specific to the observed pattern.
- Keep recommended_remediation to one specific sim suggestion."""


def _build_student_pattern_description(
    pattern_results: list[dict],
    raw_events: list[dict],
) -> str:
    """Build a description of the student's answer pattern from both sources."""
    parts = []

    if pattern_results:
        parts.append("=== Pattern-Based Detector Findings ===")
        for pr in pattern_results:
            parts.append(
                f"- Concept: {pr.get('concept', 'unknown')} "
                f"(pattern: {pr.get('pattern_type', '?')}, "
                f"confidence: {pr.get('confidence', 0):.2f})"
            )
            if pr.get("description"):
                parts.append(f"  Description: {pr['description']}")
            if pr.get("count"):
                parts.append(f"  Evidence count: {pr['count']}")
        parts.append("")

    if raw_events:
        parts.append("=== Recent Student Answer Sequence ===")
        for i, evt in enumerate(raw_events, 1):
            val = evt.get("event_value", {})
            answer_val = val
            # Flatten nested value if present
            if isinstance(val, dict) and "value" in val:
                answer_val = val["value"]

            seq_str = f"  [{i}] type={evt.get('event_type', '?')}"
            if evt.get("event_name"):
                seq_str += f" name={evt['event_name']}"
            if isinstance(answer_val, dict):
                kv_pairs = ", ".join(f"{k}={v}" for k, v in answer_val.items())
                seq_str += f" data={{{kv_pairs}}}"
            else:
                seq_str += f" value={answer_val}"
            parts.append(seq_str)

    if not parts:
        return "No interaction data available."

    return "\n".join(parts)


def _build_llm_prompt(
    sim_slug: str,
    pattern_results: list[dict],
    raw_events: list[dict],
) -> list[dict]:
    """Build the LLM message array (system + user) for the analysis."""
    # Get educational context for this sim
    sim_ctx = SIM_MISCONCEPTION_CONTEXT.get(sim_slug, {})

    educational_context_parts = []
    if sim_ctx:
        if sim_ctx.get("concept_taught"):
            educational_context_parts.append(
                f"Concept taught: {sim_ctx['concept_taught']}"
            )
        if sim_ctx.get("ngss_id"):
            educational_context_parts.append(f"NGSS Standard: {sim_ctx['ngss_id']}")
        if sim_ctx.get("ngss_description"):
            educational_context_parts.append(
                f"NGSS Description: {sim_ctx['ngss_description']}"
            )
        if sim_ctx.get("common_misconceptions"):
            educational_context_parts.append("\nCommon known misconceptions:")
            for i, mc in enumerate(sim_ctx["common_misconceptions"], 1):
                educational_context_parts.append(f"  {i}. {mc}")
    else:
        educational_context_parts.append(
            "(No specific educational context available for this simulation.)"
        )

    educational_context = "\n".join(educational_context_parts)
    student_pattern = _build_student_pattern_description(pattern_results, raw_events)

    user_message = (
        f"Simulation: {sim_slug}\n\n"
        f"=== Educational Context ===\n"
        f"{educational_context}\n\n"
        f"=== Student Interaction Pattern ===\n"
        f"{student_pattern}\n\n"
        f"Analyze the student's interaction pattern and identify any science "
        f"misconceptions. Return your analysis as JSON."
    )

    return [
        {"role": "system", "content": _AI_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


# ──────────────────────────────────────────────────────────────────────
# LLM response parsing
# ──────────────────────────────────────────────────────────────────────


def _parse_llm_response(raw: str) -> AIAnalysisOutput | None:
    """Parse the LLM JSON response into an AIAnalysisOutput.

    Handles common LLM formatting issues: markdown fences, trailing commas,
    leading/trailing whitespace, partial JSON.
    """
    content = raw.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        # Find the first newline and last ``` fence
        first_nl = content.find("\n")
        if first_nl != -1:
            content = content[first_nl + 1 :]
        if content.endswith("```"):
            content = content[:-3].strip()
        elif "```" in content:
            # Handle ```json ... ```
            start = content.find("\n") + 1
            end = content.rfind("```")
            if end > start:
                content = content[start:end].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try to fix common issues: trailing commas
        cleaned = _sanitize_json(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON: %s", raw[:200])
            return None

    misconceptions = []
    for mc in data.get("detected_misconceptions", []):
        misconceptions.append(
            AIMisconceptionResult(
                concept=mc.get("concept", "unknown"),
                specific_misconception=mc.get("specific_misconception", ""),
                confidence=min(float(mc.get("confidence", 0)), 1.0),
                explanation=mc.get("explanation", ""),
            )
        )

    # Sort by confidence descending
    misconceptions.sort(key=lambda m: m.confidence, reverse=True)

    return AIAnalysisOutput(
        detected_misconceptions=misconceptions,
        teaching_guidance=data.get("teaching_guidance"),
        recommended_remediation=data.get("recommended_remediation"),
    )


def _sanitize_json(text: str) -> str:
    """Attempt to fix common JSON formatting issues from LLM output."""
    # Remove control characters except tab, newline, and valid JSON ones
    cleaned = "".join(c for c in text if c >= " " or c in "\n\r\t")
    # Try to handle trailing commas in objects and arrays (most common LLM issue)
    import re

    # Remove trailing commas before closing braces/brackets
    cleaned = re.sub(r",\s*}", "}", cleaned)
    cleaned = re.sub(r",\s*]", "]", cleaned)
    return cleaned


# ──────────────────────────────────────────────────────────────────────
# Main public API
# ──────────────────────────────────────────────────────────────────────


async def analyze_misconceptions_ai(
    sim_slug: str,
    raw_events: list[dict],
    pattern_results: list[dict] | None = None,
) -> AIAnalysisOutput:
    """Run AI-powered misconception analysis on a student's interaction pattern.

    Args:
        sim_slug: The simulation slug to analyze.
        raw_events: Raw event dicts from the student's recent session.
        pattern_results: Optional output from the pattern-based detector
            (list of DetectionResult dicts) to provide additional context.

    Returns:
        AIAnalysisOutput with detected misconceptions, guidance, and remediation.
        If the LLM call fails or there's insufficient data, returns an empty
        AIAnalysisOutput with ai_used=False.
    """
    output = AIAnalysisOutput()

    # Edge case: not enough data
    if len(raw_events) < _MIN_EVENTS_FOR_AI:
        logger.debug(
            "Skipping AI analysis for %s: only %d events (min %d)",
            sim_slug,
            len(raw_events),
            _MIN_EVENTS_FOR_AI,
        )
        return output

    # Check if API key is configured
    api_key = settings.openai_api_key.strip() if settings.openai_api_key else ""
    if not api_key:
        logger.warning("OPENAI_API_KEY not configured — skipping AI misconception analysis")
        output.ai_error = "LLM API key not configured"
        return output

    # Build the prompt
    pattern_dicts = [p.to_dict() if hasattr(p, "to_dict") else p for p in (pattern_results or [])]
    messages = _build_llm_prompt(sim_slug, pattern_dicts, raw_events)

    try:
        client = AsyncOpenAI(api_key=api_key, timeout=30.0)

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_tokens=settings.llm_max_tokens,
            temperature=0.2,
        )

        raw = response.choices[0].message.content or ""
        if not raw.strip():
            logger.warning("LLM returned empty response for misconception analysis")
            output.ai_error = "LLM returned empty response"
            return output

        parsed = _parse_llm_response(raw)
        if parsed is None:
            logger.warning("LLM response could not be parsed for misconception analysis")
            output.ai_error = "Failed to parse LLM response"
            return output

        output.detected_misconceptions = parsed.detected_misconceptions
        output.teaching_guidance = parsed.teaching_guidance
        output.recommended_remediation = parsed.recommended_remediation
        output.ai_used = True

        logger.info(
            "AI misconception analysis for %s: %d misconceptions detected, "
            "guidance=%s, remediation=%s",
            sim_slug,
            len(output.detected_misconceptions),
            bool(output.teaching_guidance),
            bool(output.recommended_remediation),
        )

    except Exception as exc:
        logger.warning(
            "LLM misconception analysis failed for %s: %s",
            sim_slug,
            str(exc),
            exc_info=True,
        )
        output.ai_error = str(exc)

    return output


# ──────────────────────────────────────────────────────────────────────
# WebSocket flag generation
# ──────────────────────────────────────────────────────────────────────


_FLAG_CONFIDENCE_THRESHOLD = 0.6
"""AI misconceptions with confidence >= this trigger WebSocket flags."""


def generate_ws_flags(
    ai_output: AIAnalysisOutput,
    student_id: str,
    sim_slug: str,
    teacher_id: str | None = None,
) -> list[dict]:
    """Generate WebSocket flag payloads for high-confidence AI misconceptions.

    Returns a list of flag dicts suitable for broadcasting via the alert
    service. Each flag has the format expected by the live dashboard:
    {
        "flag_type": "ai_misconception",
        "message": "...",
        "metadata": {concept, specific_misconception, teaching_guidance, ...}
    }

    Args:
        ai_output: The output from analyze_misconceptions_ai().
        student_id: The student's UUID.
        sim_slug: The simulation slug.
        teacher_id: Optional teacher ID (for alert routing).

    Returns:
        List of flag dicts (may be empty).
    """
    flags: list[dict] = []

    if not ai_output.ai_used or not ai_output.detected_misconceptions:
        return flags

    for mc in ai_output.detected_misconceptions:
        if mc.confidence < _FLAG_CONFIDENCE_THRESHOLD:
            continue

        metadata: dict[str, Any] = {
            "concept": mc.concept,
            "specific_misconception": mc.specific_misconception,
            "explanation": mc.explanation,
            "confidence": mc.confidence,
            "sim_slug": sim_slug,
            "student_id": student_id,
        }

        if ai_output.teaching_guidance:
            metadata["teaching_guidance"] = ai_output.teaching_guidance
        if ai_output.recommended_remediation:
            metadata["recommended_remediation"] = ai_output.recommended_remediation
        if teacher_id:
            metadata["teacher_id"] = teacher_id

        flags.append({
            "flag_type": "ai_misconception",
            "message": (
                f"AI detected a possible misconception: {mc.specific_misconception} "
                f"({mc.concept}, confidence: {mc.confidence:.0%})"
            ),
            "metadata": metadata,
        })

    return flags
