import pytest
from pydantic import ValidationError

from app.schemas.report import (
    AISuggestionState,
    ReportCreate,
)
from app.services.report_review_service import (
    _build_ai_conflicts,
)


# ---------------------------------------------------------------------------
# I3 E4 — AI provenance.
# ---------------------------------------------------------------------------


def test_same_field_can_have_two_different_ai_sources():
    """
    Smart Report and Visual Recognition may both suggest a
    value for possible_threat.

    They are separate advisory sources and must not replace
    one another.
    """

    smart = AISuggestionState(
        field="possible_threat",
        source="smart_report",
        suggested_value="marine_debris",
        confidence=None,
        status="confirmed",
    )

    visual = AISuggestionState(
        field="possible_threat",
        source="visual_recognition",
        suggested_value="ghost_gear",
        confidence=0.84,
        status="removed",
    )

    assert smart.field == visual.field

    assert (
        smart.source
        == "smart_report"
    )

    assert (
        visual.source
        == "visual_recognition"
    )


def test_different_ai_values_create_conflict():
    """
    I3 US4.5 requires a discrepancy to be shown when text
    and visual AI suggest different values for the same
    field.
    """

    suggestions = [
        AISuggestionState(
            field="possible_threat",
            source="smart_report",
            suggested_value="marine_debris",
            confidence=None,
            status="unresolved",
        ),
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value="ghost_gear",
            confidence=0.84,
            status="unresolved",
        ),
    ]

    conflicts = _build_ai_conflicts(
        suggestions
    )

    assert len(conflicts) == 1

    conflict = conflicts[0]

    assert (
        conflict["field"]
        == "possible_threat"
    )

    assert (
        conflict["text_suggestion"]
        == "marine_debris"
    )

    assert (
        conflict["visual_suggestion"]
        == "ghost_gear"
    )

    assert (
        conflict["visual_confidence"]
        == 0.84
    )


def test_matching_ai_values_do_not_create_conflict():
    """
    Agreement between the two AI sources is not a conflict.

    Agreement still does not make the value authoritative;
    the Observer must explicitly resolve the suggestions.
    """

    suggestions = [
        AISuggestionState(
            field="possible_threat",
            source="smart_report",
            suggested_value="marine_debris",
            confidence=None,
            status="unresolved",
        ),
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value="marine_debris",
            confidence=0.91,
            status="unresolved",
        ),
    ]

    conflicts = _build_ai_conflicts(
        suggestions
    )

    assert conflicts == []


def test_ai_value_comparison_ignores_case_and_outer_whitespace():
    """
    Formatting differences must not create a false AI
    conflict.
    """

    suggestions = [
        AISuggestionState(
            field="possible_threat",
            source="smart_report",
            suggested_value=" Marine_Debris ",
            confidence=None,
            status="unresolved",
        ),
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value="marine_debris",
            confidence=0.88,
            status="unresolved",
        ),
    ]

    conflicts = _build_ai_conflicts(
        suggestions
    )

    assert conflicts == []


def test_single_ai_source_does_not_create_conflict():
    """
    Conflict means disagreement between sources.

    One available AI suggestion on its own is therefore not
    a conflict.
    """

    suggestions = [
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value="ghost_gear",
            confidence=0.72,
            status="unresolved",
        )
    ]

    conflicts = _build_ai_conflicts(
        suggestions
    )

    assert conflicts == []


def test_missing_ai_value_does_not_create_conflict():
    """
    An unsure/unavailable AI source with no usable value is
    not treated as a value-to-value disagreement.
    """

    suggestions = [
        AISuggestionState(
            field="possible_threat",
            source="smart_report",
            suggested_value="marine_debris",
            confidence=None,
            status="unresolved",
        ),
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value=None,
            confidence=None,
            status="removed",
        ),
    ]

    conflicts = _build_ai_conflicts(
        suggestions
    )

    assert conflicts == []


# ---------------------------------------------------------------------------
# Source-specific contract.
# ---------------------------------------------------------------------------


def test_smart_report_confidence_must_be_null():
    """
    Smart Report currently does not expose a numeric
    confidence compatible with Visual Recognition.
    """

    with pytest.raises(
        ValidationError
    ):
        AISuggestionState(
            field="possible_threat",
            source="smart_report",
            suggested_value="marine_debris",
            confidence=0.90,
            status="confirmed",
        )


def test_visual_recognition_accepts_confidence():
    suggestion = AISuggestionState(
        field="possible_threat",
        source="visual_recognition",
        suggested_value="marine_debris",
        confidence=0.90,
        status="confirmed",
    )

    assert suggestion.confidence == 0.90


def test_visual_confidence_above_one_is_rejected():
    with pytest.raises(
        ValidationError
    ):
        AISuggestionState(
            field="possible_threat",
            source="visual_recognition",
            suggested_value="marine_debris",
            confidence=1.01,
            status="confirmed",
        )


def test_unknown_ai_source_is_rejected():
    with pytest.raises(
        ValidationError
    ):
        AISuggestionState(
            field="possible_threat",
            source="unknown_ai",
            suggested_value="marine_debris",
            confidence=None,
            status="confirmed",
        )


# ---------------------------------------------------------------------------
# Submission boundary.
# ---------------------------------------------------------------------------


def _valid_report_payload():
    return {
        "threat_category_id": 1,
        "observed_at":
            "2026-09-01T10:00:00+08:00",
        "estimated_depth_metres": 8,
        "description":
            "Visible debris was observed on the reef.",
        "dive_session_id": 1,
        "location": {
            "named_dive_site_id": 1,
            "location_confidence":
                "dive_site_only",
            "location_source":
                "named_dive_site",
        },
        "evidence_metadata": [],
    }


def test_unresolved_smart_report_suggestion_blocks_submission():
    payload = _valid_report_payload()

    payload["ai_suggestions"] = [
        {
            "field":
                "possible_threat",
            "source":
                "smart_report",
            "suggested_value":
                "marine_debris",
            "confidence":
                None,
            "status":
                "unresolved",
        }
    ]

    with pytest.raises(
        ValidationError
    ):
        ReportCreate(
            **payload
        )


def test_unresolved_visual_suggestion_blocks_submission():
    payload = _valid_report_payload()

    payload["ai_suggestions"] = [
        {
            "field":
                "possible_threat",
            "source":
                "visual_recognition",
            "suggested_value":
                "ghost_gear",
            "confidence":
                0.81,
            "status":
                "unresolved",
        }
    ]

    with pytest.raises(
        ValidationError
    ):
        ReportCreate(
            **payload
        )


def test_resolved_conflicting_ai_suggestions_allow_report_model():
    """
    The AI systems may originally disagree.

    Once the Observer explicitly resolves both suggestions,
    disagreement itself must not block submission.

    threat_category_id remains the canonical final choice.
    """

    payload = _valid_report_payload()

    payload["ai_suggestions"] = [
        {
            "field":
                "possible_threat",
            "source":
                "smart_report",
            "suggested_value":
                "marine_debris",
            "confidence":
                None,
            "status":
                "confirmed",
        },
        {
            "field":
                "possible_threat",
            "source":
                "visual_recognition",
            "suggested_value":
                "ghost_gear",
            "confidence":
                0.84,
            "status":
                "removed",
        },
    ]

    report = ReportCreate(
        **payload
    )

    assert (
        report.threat_category_id
        == 1
    )

    assert (
        len(report.ai_suggestions)
        == 2
    )