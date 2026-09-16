import json
from urllib import request

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import smart_report_service


class _FakeProviderResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"status":"completed","steps":[]}'


@pytest.mark.asyncio
async def test_returns_manual_fallback_without_api_key(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        None,
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "A fishing net was tangled around coral."
        )
    )

    assert result.available is False
    assert result.suggestions == []
    assert "manually" in result.message.lower()


@pytest.mark.asyncio
async def test_maps_valid_model_output_to_reviewable_suggestions(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    model_output = {
        "possible_threat": "ghost fishing gear",
        "estimated_depth_metres": "about 15 metres",
        "approximate_size": None,
        "coral_interaction": "net tangled around coral",
        "animal_interaction": None,
        "site_reference": None,
        "missing_information": [
            "approximate size",
            "animal interaction",
        ],
    }
    monkeypatch.setattr(
        smart_report_service,
        "_post_json",
        lambda payload: {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                model_output
                            ),
                        }
                    ]
                }
            ]
        },
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "A fishing net was tangled around coral at 15 metres."
        )
    )

    assert result.available is True
    assert [
        suggestion.field
        for suggestion in result.suggestions
    ] == [
        "possible_threat",
        "estimated_depth_metres",
        "coral_interaction",
    ]
    assert result.missing_information == [
        "approximate size",
        "animal interaction",
    ]
    assert [
        question.field
        for question in result.follow_up_questions
    ] == [
        "approximate_size",
        "animal_interaction",
    ]
    assert result.follow_up_questions[0].options == [
        "<1 m",
        "1-5 m",
        "5-10 m",
        ">10 m",
        "Unsure",
    ]
    assert result.requires_user_confirmation is True


@pytest.mark.asyncio
async def test_uses_not_specified_instead_of_guessing_threat(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        smart_report_service,
        "_post_json",
        lambda payload: {
            "output_text": json.dumps(
                {
                    "possible_threat": None,
                    "estimated_depth_metres": None,
                    "approximate_size": None,
                    "coral_interaction": None,
                    "animal_interaction": None,
                    "site_reference": None,
                    "missing_information": [
                        "possible threat",
                    ],
                }
            )
        },
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "Something unusual was visible near the reef."
        )
    )

    assert result.suggestions[0].field == (
        "possible_threat"
    )
    assert result.suggestions[0].suggested_value == (
        "Not specified"
    )
    assert result.follow_up_questions == []


@pytest.mark.asyncio
async def test_skips_follow_up_for_information_already_extracted(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        smart_report_service,
        "_post_json",
        lambda payload: {
            "output_text": json.dumps(
                {
                    "possible_threat": "coral bleaching",
                    "estimated_depth_metres": None,
                    "approximate_size": "several colonies",
                    "coral_interaction": None,
                    "animal_interaction": None,
                    "site_reference": None,
                    "missing_information": [],
                }
            )
        },
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "Several coral colonies looked pale or white."
        )
    )

    assert result.available is True
    assert result.follow_up_questions == []


@pytest.mark.asyncio
async def test_uses_controlled_question_for_physical_damage(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        smart_report_service,
        "_post_json",
        lambda payload: {
            "output_text": json.dumps(
                {
                    "possible_threat": "physical reef damage",
                    "estimated_depth_metres": None,
                    "approximate_size": None,
                    "coral_interaction": None,
                    "animal_interaction": None,
                    "site_reference": None,
                    "missing_information": [
                        "appearance of the damage",
                    ],
                }
            )
        },
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "I saw recently damaged coral near the reef."
        )
    )

    assert len(result.follow_up_questions) == 1
    question = result.follow_up_questions[0]
    assert question.field == "coral_interaction"
    assert question.question == (
        "What did the damage look like?"
    )
    assert "Collision damage" in question.options


def test_normalises_supported_threat_wording_safely():
    assert smart_report_service._normalise_threat(
        "Ghost-fishing gear."
    ) == "ghost fishing gear"
    assert smart_report_service._normalise_threat(
        "an unsupported diagnosis"
    ) is None


def test_provider_payload_excludes_photos_and_location():
    payload = smart_report_service._provider_payload(
        "Plastic debris beside the coral."
    )

    assert payload["input"] == (
        "Plastic debris beside the coral."
    )
    assert payload["model"] == (
        "gemini-3.1-flash-lite"
    )
    assert payload["response_format"]["mime_type"] == (
        "application/json"
    )
    encoded = json.dumps(payload).lower()
    assert "image_url" not in encoded
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "do not create follow-up questions" in encoded


def test_posts_to_gemini_interactions_with_secret_header(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("gemini-test-key"),
    )
    captured = {}

    def fake_urlopen(provider_request, timeout):
        captured["request"] = provider_request
        captured["timeout"] = timeout
        return _FakeProviderResponse()

    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    result = smart_report_service._post_json(
        smart_report_service._provider_payload(
            "Plastic debris beside the coral."
        )
    )

    provider_request = captured["request"]
    assert provider_request.full_url == (
        "https://generativelanguage.googleapis.com/"
        "v1beta/interactions"
    )
    assert provider_request.get_header(
        "X-goog-api-key"
    ) == "gemini-test-key"
    assert "gemini-test-key" not in (
        provider_request.full_url
    )
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_provider_output_falls_back_safely(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        smart_report_service,
        "_post_json",
        lambda payload: {"output_text": "not-json"},
    )

    result = await (
        smart_report_service
        .structure_report_description(
            "A fishing net was tangled around coral."
        )
    )

    assert result.available is False
    assert "manually" in result.message.lower()
