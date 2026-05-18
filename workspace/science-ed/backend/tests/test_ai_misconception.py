"""Tests for AI-powered misconception analysis — LLM prompt construction,
response parsing, edge case handling, and WebSocket flag generation.

Tests use mocked OpenAI calls to avoid actual API calls.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.misconception_context import SIM_MISCONCEPTION_CONTEXT
from app.services.ai_misconception_analyzer import (
    AIAnalysisOutput,
    AIMisconceptionResult,
    _build_llm_prompt,
    _parse_llm_response,
    _sanitize_json,
    _build_student_pattern_description,
    analyze_misconceptions_ai,
    generate_ws_flags,
    _MIN_EVENTS_FOR_AI,
    _FLAG_CONFIDENCE_THRESHOLD,
)
from app.schemas.misconception import AIMisconceptionResult as AIMisconceptionResultSchema
from app.schemas.misconception import AIMisconceptionAnalysis


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_openai():
    """Patch AsyncOpenAI.chat.completions.create to return a canned response."""
    with patch("app.services.ai_misconception_analyzer.AsyncOpenAI") as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value = mock_instance

        # Set the openai_api_key to avoid the 'not configured' early return
        with patch("app.services.ai_misconception_analyzer.settings.openai_api_key", "sk-test-key"):
            yield mock_instance


def _make_mock_completion(content: str) -> MagicMock:
    """Build a mock ChatCompletion response with the given content string."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _sign_error_events(n: int = 3) -> list[dict]:
    """Generate n events where student consistently gets net_force_direction wrong."""
    events = []
    for i in range(n):
        events.append(
            {
                "event_type": "sim_interaction",
                "event_name": "answer_submit",
                "event_value": {
                    "value": {
                        "net_force_direction": "opposite",
                        "question": "river_crossing_q1",
                    }
                },
                "client_ts": f"2025-01-0{i+1}T10:00:00Z",
            }
        )
    return events


def _oscillating_events(n: int = 4) -> list[dict]:
    """Generate n events where student oscillates between two wrong answers."""
    wrongs = ["changes_substance", "number_of_molecules"]
    events = []
    for i in range(n):
        events.append(
            {
                "event_type": "sim_interaction",
                "event_name": "answer_submit",
                "event_value": {
                    "value": {
                        "coefficient_meaning": wrongs[i % 2],
                        "question": "balancing_eq1",
                    }
                },
                "client_ts": f"2025-01-0{i+1}T10:00:00Z",
            }
        )
    return events


def _correct_events(n: int = 3) -> list[dict]:
    """Generate n events where student answers everything correctly."""
    events = []
    for i in range(n):
        events.append(
            {
                "event_type": "sim_interaction",
                "event_name": "answer_submit",
                "event_value": {
                    "value": {
                        "conservation_matter": "rearranged",
                        "question": "conservation_q1",
                        "score": 1.0,
                    }
                },
                "client_ts": f"2025-01-0{i+1}T10:00:00Z",
            }
        )
    return events


# ──────────────────────────────────────────────────────────────────────
# Sanitize JSON
# ──────────────────────────────────────────────────────────────────────


class TestSanitizeJson:
    def test_trailing_comma_in_object(self):
        raw = '{"a": 1, "b": 2,}'
        assert _sanitize_json(raw) == '{"a": 1, "b": 2}'

    def test_trailing_comma_in_array(self):
        raw = '{"items": [1, 2, 3,]}'
        assert _sanitize_json(raw) == '{"items": [1, 2, 3]}'

    def test_trailing_comma_nested(self):
        raw = '{"a": {"b": 1,}, "c": [1, 2,],}'
        expected = '{"a": {"b": 1}, "c": [1, 2]}'
        assert _sanitize_json(raw) == expected

    def test_clean_json_unchanged(self):
        raw = '{"a": 1, "b": 2}'
        assert _sanitize_json(raw) == raw

    def test_control_characters_removed(self):
        raw = '{"a": 1\x00, "b": 2}'
        cleaned = _sanitize_json(raw)
        assert "\x00" not in cleaned
        assert json.loads(cleaned)


# ──────────────────────────────────────────────────────────────────────
# LLM Response Parsing
# ──────────────────────────────────────────────────────────────────────


class TestParseLlmResponse:
    def test_parse_valid_json(self):
        raw = json.dumps(
            {
                "detected_misconceptions": [
                    {
                        "concept": "velocity-vs-acceleration",
                        "specific_misconception": "Student confuses velocity with acceleration",
                        "confidence": 0.87,
                        "explanation": "Consistently sets initial velocity to 9.8.",
                    }
                ],
                "teaching_guidance": "Review the difference between velocity and acceleration.",
                "recommended_remediation": "Assign Forces and Motion sim.",
            }
        )
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result.detected_misconceptions) == 1
        assert result.detected_misconceptions[0].concept == "velocity-vs-acceleration"
        assert result.detected_misconceptions[0].confidence == 0.87
        assert result.teaching_guidance == "Review the difference between velocity and acceleration."
        assert result.recommended_remediation == "Assign Forces and Motion sim."

    def test_parse_with_markdown_fence(self):
        raw = f"```json\n{json.dumps({'detected_misconceptions': [], 'teaching_guidance': None, 'recommended_remediation': None})}\n```"
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result.detected_misconceptions) == 0

    def test_parse_with_trailing_comma(self):
        raw = '{"detected_misconceptions": [{"concept": "test", "specific_misconception": "x", "confidence": 0.5, "explanation": "y",}], "teaching_guidance": "g", "recommended_remediation": "r"}'
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result.detected_misconceptions) == 1

    def test_parse_empty_misconceptions(self):
        raw = json.dumps(
            {
                "detected_misconceptions": [],
                "teaching_guidance": None,
                "recommended_remediation": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result is not None
        assert len(result.detected_misconceptions) == 0

    def test_parse_sorts_by_confidence(self):
        data = {
            "detected_misconceptions": [
                {"concept": "a", "specific_misconception": "x", "confidence": 0.5, "explanation": "e"},
                {"concept": "b", "specific_misconception": "y", "confidence": 0.9, "explanation": "f"},
                {"concept": "c", "specific_misconception": "z", "confidence": 0.7, "explanation": "g"},
            ],
            "teaching_guidance": None,
            "recommended_remediation": None,
        }
        result = _parse_llm_response(json.dumps(data))
        assert result is not None
        confidences = [m.confidence for m in result.detected_misconceptions]
        assert confidences == [0.9, 0.7, 0.5]

    def test_parse_invalid_json_returns_none(self):
        result = _parse_llm_response("this is not json")
        assert result is None

    def test_parse_empty_string_returns_none(self):
        result = _parse_llm_response("")
        assert result is None

    def test_parse_confidence_capped_at_1(self):
        raw = json.dumps(
            {
                "detected_misconceptions": [
                    {
                        "concept": "test",
                        "specific_misconception": "x",
                        "confidence": 99.0,
                        "explanation": "y",
                    }
                ],
                "teaching_guidance": None,
                "recommended_remediation": None,
            }
        )
        result = _parse_llm_response(raw)
        assert result is not None
        assert result.detected_misconceptions[0].confidence == 1.0

    def test_parse_missing_fields_defaults(self):
        raw = json.dumps(
            {
                "detected_misconceptions": [
                    {"concept": "test", "confidence": 0.7}
                ]
            }
        )
        result = _parse_llm_response(raw)
        assert result is not None
        assert result.detected_misconceptions[0].specific_misconception == ""
        assert result.detected_misconceptions[0].explanation == ""
        assert result.teaching_guidance is None
        assert result.recommended_remediation is None


# ──────────────────────────────────────────────────────────────────────
# Prompt Construction
# ──────────────────────────────────────────────────────────────────────


class TestBuildLlmPrompt:
    def test_includes_sim_context(self):
        events = _sign_error_events(3)
        for sim_slug in SIM_MISCONCEPTION_CONTEXT:
            messages = _build_llm_prompt(sim_slug, [], events)
            assert len(messages) == 2  # system + user
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"

            # Verify the sim's concept is mentioned
            ctx = SIM_MISCONCEPTION_CONTEXT[sim_slug]
            if ctx.get("ngss_id"):
                assert ctx["ngss_id"] in messages[1]["content"]
            if ctx.get("concept_taught"):
                # Check at least some of the concept text is there
                concept_preview = ctx["concept_taught"][:50]
                assert concept_preview in messages[1]["content"]

    def test_includes_pattern_results(self):
        pattern_results = [
            {
                "concept": "velocity-vs-acceleration",
                "pattern_type": "repeated_error",
                "confidence": 0.85,
                "description": "Student confuses velocity with acceleration",
                "count": 3,
            }
        ]
        events = _sign_error_events(3)
        messages = _build_llm_prompt("projectile-motion-simulation", pattern_results, events)
        user_msg = messages[1]["content"]

        assert "velocity-vs-acceleration" in user_msg
        assert "repeated_error" in user_msg
        assert "0.85" in user_msg

    def test_includes_raw_events(self):
        events = _sign_error_events(3)
        messages = _build_llm_prompt("projectile-motion-simulation", [], events)
        user_msg = messages[1]["content"]

        # Should mention the answer values
        assert "opposite" in user_msg or "answer_submit" in user_msg

    def test_no_data_handling(self):
        messages = _build_llm_prompt("unknown-sim", [], [])
        user_msg = messages[1]["content"]
        assert "No interaction data available" in user_msg
        assert "No specific educational context" in user_msg


class TestBuildStudentPatternDescription:
    def test_with_pattern_results_and_events(self):
        patterns = [
            {
                "concept": "velocity-vs-acceleration",
                "pattern_type": "repeated_error",
                "confidence": 0.85,
                "description": "Some description",
                "count": 3,
            }
        ]
        events = _sign_error_events(2)
        desc = _build_student_pattern_description(patterns, events)
        assert "Pattern-Based Detector Findings" in desc
        assert "velocity-vs-acceleration" in desc
        assert "repeated_error" in desc
        assert "Recent Student Answer Sequence" in desc

    def test_no_data(self):
        desc = _build_student_pattern_description([], [])
        assert desc == "No interaction data available."


# ──────────────────────────────────────────────────────────────────────
# AI Analysis (with mocked LLM)
# ──────────────────────────────────────────────────────────────────────


class TestAnalyzeMisconceptionsAi:
    @pytest.mark.asyncio
    async def test_detects_sign_error_pattern(self, mock_openai):
        """Student with consistent sign-error pattern → AI detects 'confuses direction of force'."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion(
            json.dumps(
                {
                    "detected_misconceptions": [
                        {
                            "concept": "net-force-direction",
                            "specific_misconception": "Student consistently identifies net force in the wrong direction, confusing individual forces with net force",
                            "confidence": 0.82,
                            "explanation": "The student consistently selects 'opposite' for net force direction across multiple questions, suggesting they are confusing one component force with the vector sum.",
                        }
                    ],
                    "teaching_guidance": "Review the concept of net force as the vector sum of all forces. Use the simulation's vector overlay to show how individual forces combine.",
                    "recommended_remediation": "Assign the 'Forces and Motion' simulation to reinforce vector addition of forces.",
                }
            )
        )

        events = _sign_error_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="interactive-boat-river-crossing-simulation",
            raw_events=events,
            pattern_results=[
                {
                    "concept": "net-force-direction",
                    "pattern_type": "sign_error",
                    "confidence": 0.65,
                    "count": 3,
                    "description": "Student consistently identifies net force in the wrong direction.",
                }
            ],
        )

        assert result.ai_used is True
        assert len(result.detected_misconceptions) == 1
        assert result.detected_misconceptions[0].concept == "net-force-direction"
        assert result.detected_misconceptions[0].confidence == 0.82
        assert result.teaching_guidance is not None
        assert result.recommended_remediation is not None

    @pytest.mark.asyncio
    async def test_detects_oscillating_pattern(self, mock_openai):
        """Student oscillating between wrong answers → AI detects uncertainty."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion(
            json.dumps(
                {
                    "detected_misconceptions": [
                        {
                            "concept": "coefficients-change-substance",
                            "specific_misconception": "Student is guessing between two incorrect interpretations of chemical equation coefficients",
                            "confidence": 0.75,
                            "explanation": "The student alternates between believing coefficients change the substance and correctly identifying them as molecule counts, showing uncertain understanding.",
                        }
                    ],
                    "teaching_guidance": "Practice balancing equations with manipulatives to show coefficients represent molecule counts.",
                    "recommended_remediation": "Assign the balancing chemical equations activity.",
                }
            )
        )

        events = _oscillating_events(4)
        result = await analyze_misconceptions_ai(
            sim_slug="chemical-reactions-outcomes",
            raw_events=events,
            pattern_results=[],
        )

        assert result.ai_used is True
        assert len(result.detected_misconceptions) == 1
        assert result.detected_misconceptions[0].concept == "coefficients-change-substance"

    @pytest.mark.asyncio
    async def test_empty_for_correct_student(self, mock_openai):
        """Student who gets everything right → AI returns empty misconceptions list."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion(
            json.dumps(
                {
                    "detected_misconceptions": [],
                    "teaching_guidance": None,
                    "recommended_remediation": None,
                }
            )
        )

        events = _correct_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="chemical-reactions-outcomes",
            raw_events=events,
        )

        assert result.ai_used is True
        assert len(result.detected_misconceptions) == 0

    @pytest.mark.asyncio
    async def test_skips_with_less_than_min_events(self, mock_openai):
        """Student has < 3 answer events → skip AI analysis."""
        events = _sign_error_events(1)  # only 1 event
        result = await analyze_misconceptions_ai(
            sim_slug="projectile-motion-simulation",
            raw_events=events,
        )
        assert result.ai_used is False
        assert len(result.detected_misconceptions) == 0
        # LLM should never be called
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_no_events(self, mock_openai):
        """Student hasn't answered any questions → return empty, don't call LLM."""
        result = await analyze_misconceptions_ai(
            sim_slug="projectile-motion-simulation",
            raw_events=[],
        )
        assert result.ai_used is False
        assert len(result.detected_misconceptions) == 0
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, mock_openai):
        """LLM call fails → fall back gracefully with ai_used=False."""
        mock_openai.chat.completions.create.side_effect = Exception("API timeout")

        events = _sign_error_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="interactive-boat-river-crossing-simulation",
            raw_events=events,
        )

        assert result.ai_used is False
        assert result.ai_error is not None
        assert len(result.detected_misconceptions) == 0

    @pytest.mark.asyncio
    async def test_fallback_on_empty_llm_response(self, mock_openai):
        """LLM returns empty string → fall back gracefully."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion("")

        events = _sign_error_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="projectile-motion-simulation",
            raw_events=events,
        )

        assert result.ai_used is False
        assert result.ai_error == "LLM returned empty response"

    @pytest.mark.asyncio
    async def test_no_api_key_skips_gracefully(self, mock_openai):
        """No API key configured → skip AI with clear message."""
        with patch("app.services.ai_misconception_analyzer.settings.openai_api_key", ""):
            events = _sign_error_events(3)
            result = await analyze_misconceptions_ai(
                sim_slug="projectile-motion-simulation",
                raw_events=events,
            )

        assert result.ai_used is False
        assert result.ai_error == "LLM API key not configured"
        # AsyncOpenAI should never have been called
        mock_openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_misconceptions_sorted(self, mock_openai):
        """Multiple misconceptions detected → sorted by confidence descending."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion(
            json.dumps(
                {
                    "detected_misconceptions": [
                        {
                            "concept": "low",
                            "specific_misconception": "Minor confusion",
                            "confidence": 0.45,
                            "explanation": "Some minor issue.",
                        },
                        {
                            "concept": "high",
                            "specific_misconception": "Major misconception",
                            "confidence": 0.92,
                            "explanation": "Serious misunderstanding.",
                        },
                        {
                            "concept": "medium",
                            "specific_misconception": "Moderate issue",
                            "confidence": 0.65,
                            "explanation": "Moderate misunderstanding.",
                        },
                    ],
                    "teaching_guidance": "Focus on the core concept.",
                    "recommended_remediation": "Assign remediation sim.",
                }
            )
        )

        events = _sign_error_events(5)
        result = await analyze_misconceptions_ai(
            sim_slug="projectile-motion-simulation",
            raw_events=events,
        )

        # Only entries > 0.4 are returned (per guidelines, low=0.45 is included)
        assert len(result.detected_misconceptions) == 3
        confidences = [m.confidence for m in result.detected_misconceptions]
        assert confidences == [0.92, 0.65, 0.45]

    @pytest.mark.asyncio
    async def test_llm_response_with_markdown_fence(self, mock_openai):
        """LLM returns JSON wrapped in markdown code fence → still parsed correctly."""
        response_data = {
            "detected_misconceptions": [
                {
                    "concept": "amplitude-frequency-confusion",
                    "specific_misconception": "Student confuses amplitude with frequency",
                    "confidence": 0.78,
                    "explanation": "Thinks higher amplitude means higher frequency.",
                }
            ],
            "teaching_guidance": "Use the wave simulator to demonstrate amplitude vs frequency independently.",
            "recommended_remediation": "Assign wave superposition sim.",
        }
        raw = f"```json\n{json.dumps(response_data)}\n```"
        mock_openai.chat.completions.create.return_value = _make_mock_completion(raw)

        events = _sign_error_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="wave-superposition-3-d",
            raw_events=events,
        )

        assert result.ai_used is True
        assert len(result.detected_misconceptions) == 1
        assert result.detected_misconceptions[0].concept == "amplitude-frequency-confusion"

    @pytest.mark.asyncio
    async def test_without_pattern_results(self, mock_openai):
        """Works without pattern-based detector results."""
        mock_openai.chat.completions.create.return_value = _make_mock_completion(
            json.dumps(
                {
                    "detected_misconceptions": [
                        {
                            "concept": "heavier-falls-faster",
                            "specific_misconception": "Student thinks heavier objects fall faster",
                            "confidence": 0.71,
                            "explanation": "Pattern suggests Aristotelian gravity misconception.",
                        }
                    ],
                    "teaching_guidance": "Demo with feather and hammer in vacuum.",
                    "recommended_remediation": "Assign gravity sim.",
                }
            )
        )

        events = _sign_error_events(3)
        result = await analyze_misconceptions_ai(
            sim_slug="projectile-motion-simulation",
            raw_events=events,
            pattern_results=None,
        )

        assert result.ai_used is True
        assert len(result.detected_misconceptions) == 1


# ──────────────────────────────────────────────────────────────────────
# WebSocket Flag Generation
# ──────────────────────────────────────────────────────────────────────


class TestGenerateWsFlags:
    def test_generates_flag_for_high_confidence(self):
        ai_output = AIAnalysisOutput(
            detected_misconceptions=[
                AIMisconceptionResult(
                    concept="net-force-direction",
                    specific_misconception="Student confuses net force direction",
                    confidence=0.82,
                    explanation="Consistent wrong direction selection.",
                )
            ],
            teaching_guidance="Review vector addition of forces.",
            recommended_remediation="Assign Forces and Motion sim.",
            ai_used=True,
        )

        flags = generate_ws_flags(ai_output, "student-123", "interactive-boat-river-crossing-simulation", "teacher-456")
        assert len(flags) == 1
        assert flags[0]["flag_type"] == "ai_misconception"
        assert "net-force-direction" in flags[0]["message"]
        assert flags[0]["metadata"]["concept"] == "net-force-direction"
        assert flags[0]["metadata"]["confidence"] == 0.82
        assert flags[0]["metadata"]["teaching_guidance"] == "Review vector addition of forces."
        assert flags[0]["metadata"]["recommended_remediation"] == "Assign Forces and Motion sim."
        assert flags[0]["metadata"]["teacher_id"] == "teacher-456"
        assert flags[0]["metadata"]["student_id"] == "student-123"

    def test_no_flag_below_threshold(self):
        ai_output = AIAnalysisOutput(
            detected_misconceptions=[
                AIMisconceptionResult(
                    concept="test",
                    specific_misconception="Low confidence",
                    confidence=0.4,  # below threshold 0.6
                    explanation="Speculative.",
                )
            ],
            ai_used=True,
        )

        flags = generate_ws_flags(ai_output, "student-123", "test-sim")
        assert len(flags) == 0

    def test_no_flags_for_empty_misconceptions(self):
        ai_output = AIAnalysisOutput(detected_misconceptions=[], ai_used=True)
        flags = generate_ws_flags(ai_output, "student-123", "test-sim")
        assert len(flags) == 0

    def test_no_flags_when_ai_not_used(self):
        ai_output = AIAnalysisOutput(detected_misconceptions=[], ai_used=False)
        flags = generate_ws_flags(ai_output, "student-123", "test-sim")
        assert len(flags) == 0

    def test_multiple_flags_generated(self):
        ai_output = AIAnalysisOutput(
            detected_misconceptions=[
                AIMisconceptionResult(
                    concept="a", specific_misconception="X", confidence=0.9, explanation="E1"
                ),
                AIMisconceptionResult(
                    concept="b", specific_misconception="Y", confidence=0.7, explanation="E2"
                ),
                AIMisconceptionResult(
                    concept="c", specific_misconception="Z", confidence=0.3, explanation="E3"
                ),
            ],
            ai_used=True,
        )

        flags = generate_ws_flags(ai_output, "student-123", "test-sim")
        # Only a and b are above the threshold
        assert len(flags) == 2


# ──────────────────────────────────────────────────────────────────────
# Schema Validation
# ──────────────────────────────────────────────────────────────────────


class TestAIMisconceptionResultSchema:
    def test_valid_schema(self):
        data = {
            "concept": "velocity-vs-acceleration",
            "specific_misconception": "Student confuses velocity with acceleration",
            "confidence": 0.87,
            "explanation": "Student consistently enters 9.8 as initial velocity.",
        }
        schema = AIMisconceptionResultSchema(**data)
        assert schema.concept == "velocity-vs-acceleration"
        assert schema.confidence == 0.87

    def test_minimal_schema(self):
        data = {
            "concept": "test",
            "specific_misconception": "desc",
            "confidence": 0.0,
            "explanation": "exp",
        }
        schema = AIMisconceptionResultSchema(**data)
        assert schema.confidence == 0.0


class TestAIMisconceptionAnalysisSchema:
    def test_full_response(self):
        data = {
            "detected_misconceptions": [
                {
                    "concept": "test",
                    "specific_misconception": "desc",
                    "confidence": 0.8,
                    "explanation": "exp",
                }
            ],
            "teaching_guidance": "Do this.",
            "recommended_remediation": "Assign that.",
            "ai_used": True,
        }
        schema = AIMisconceptionAnalysis(**data)
        assert len(schema.detected_misconceptions) == 1
        assert schema.teaching_guidance == "Do this."
        assert schema.recommended_remediation == "Assign that."
        assert schema.ai_used is True

    def test_empty_misconceptions(self):
        data = {
            "detected_misconceptions": [],
            "teaching_guidance": None,
            "recommended_remediation": None,
            "ai_used": False,
        }
        schema = AIMisconceptionAnalysis(**data)
        assert len(schema.detected_misconceptions) == 0
        assert schema.ai_used is False


# ──────────────────────────────────────────────────────────────────────
# Misconception Context Library
# ──────────────────────────────────────────────────────────────────────


class TestMisconceptionContextData:
    def test_all_five_pilot_sims_present(self):
        expected_sims = {
            "projectile-motion-simulation",
            "conservation-of-momentum-simulation",
            "wave-superposition-3-d",
            "chemical-reactions-outcomes",
            "interactive-boat-river-crossing-simulation",
        }
        assert expected_sims.issubset(SIM_MISCONCEPTION_CONTEXT.keys())

    def test_each_sim_has_required_fields(self):
        for slug, ctx in SIM_MISCONCEPTION_CONTEXT.items():
            assert "concept_taught" in ctx, f"{slug} missing concept_taught"
            assert "ngss_id" in ctx, f"{slug} missing ngss_id"
            assert "common_misconceptions" in ctx, f"{slug} missing common_misconceptions"
            assert isinstance(ctx["common_misconceptions"], list), f"{slug} misconceptions not a list"
            assert len(ctx["common_misconceptions"]) >= 1, f"{slug} has no misconceptions"
            assert "typical_wrong_answers" in ctx, f"{slug} missing typical_wrong_answers"

    def test_typical_wrong_answers_are_structured(self):
        for slug, ctx in SIM_MISCONCEPTION_CONTEXT.items():
            for field, info in ctx["typical_wrong_answers"].items():
                assert "incorrect_values" in info, f"{slug}/{field} missing incorrect_values"
                assert "correct_value" in info, f"{slug}/{field} missing correct_value"
                # At least one explanation field
                has_why = any(k.startswith("why_wrong") for k in info)
                assert has_why, f"{slug}/{field} missing why_wrong explanation"
