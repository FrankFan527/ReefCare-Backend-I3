from app.services.case_service import (
    _build_ai_assisted_context,
)


def test_visual_recognition_keeps_its_own_source():
    context = (
        _build_ai_assisted_context(
            [
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
                        "confirmed",
                }
            ]
        )
    )

    assert context.available is True

    assert (
        context.source
        == "visual_recognition"
    )

    assert (
        len(context.suggestions)
        == 1
    )

    suggestion = (
        context.suggestions[0]
    )

    assert (
        suggestion.source
        == "visual_recognition"
    )

    assert (
        suggestion.confidence
        == 0.84
    )

    assert (
        suggestion.value
        == "ghost_gear"
    )


def test_smart_report_keeps_its_own_source():
    context = (
        _build_ai_assisted_context(
            [
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
                        "corrected",
                }
            ]
        )
    )

    assert (
        context.source
        == "smart_report"
    )

    suggestion = (
        context.suggestions[0]
    )

    assert (
        suggestion.source
        == "smart_report"
    )

    assert (
        suggestion.confidence
        is None
    )


def test_mixed_ai_sources_are_not_labelled_as_smart_report():
    context = (
        _build_ai_assisted_context(
            [
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
                        "corrected",
                },
            ]
        )
    )

    assert (
        context.source
        == "mixed"
    )

    assert [
        suggestion.source
        for suggestion
        in context.suggestions
    ] == [
        "smart_report",
        "visual_recognition",
    ]


def test_empty_ai_context_has_no_source():
    context = (
        _build_ai_assisted_context(
            []
        )
    )

    assert (
        context.available
        is False
    )

    assert context.source is None

    assert (
        context.suggestions
        == []
    )

def test_camel_case_fields_get_readable_labels_and_threat_codes_their_names():
    # QA-AI-01. Visual Recognition and older payloads store
    # camelCase field names and threat category codes.
    context = _build_ai_assisted_context(
        [
            {"field": "threatCategory", "source": "visual_recognition",
             "suggested_value": "ghost_gear", "confidence": 0.81, "status": "confirmed"},
            {"field": "estimatedDepthMetres", "source": "smart_report",
             "suggested_value": "10", "confidence": None, "status": "corrected"},
            {"field": "possible_threat", "source": "smart_report",
             "suggested_value": "coral bleaching", "confidence": None, "status": "confirmed"},
            {"field": "water_visibility", "source": "smart_report",
             "suggested_value": "5 m", "confidence": None, "status": "confirmed"},
        ],
        {"ghost_gear": "Ghost fishing gear", "coral_bleaching": "Coral bleaching"},
    )

    shown = [(item.field, item.label, item.value) for item in context.suggestions]

    assert shown == [
        ("threatCategory", "Threat type", "Ghost fishing gear"),
        ("estimatedDepthMetres", "Estimated depth", "10"),
        # free text is not a code, so it is left as the Observer saw it
        ("possible_threat", "Possible threat", "coral bleaching"),
        # an unknown field still gets a readable label, never the raw key
        ("water_visibility", "Water visibility", "5 m"),
    ]


def test_unknown_threat_code_is_left_unchanged():
    context = _build_ai_assisted_context(
        [{"field": "threatCategory", "source": "visual_recognition",
          "suggested_value": "retired_code", "confidence": None, "status": "confirmed"}],
        {"ghost_gear": "Ghost fishing gear"},
    )

    assert context.suggestions[0].value == "retired_code"
