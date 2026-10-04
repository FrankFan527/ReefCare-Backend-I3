import base64
import json
from urllib import request

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services import visual_recognition_service


class _FakeProviderResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"status":"completed","steps":[]}'


@pytest.mark.asyncio
async def test_returns_non_blocking_fallback_without_api_key(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        None,
    )

    result = await (
        visual_recognition_service.recognize_visual_threat(
            content=b"image",
            content_type="image/jpeg",
        )
    )

    assert result.status == "unavailable"
    assert result.suggested_threat is None
    assert result.confidence is None
    assert "continue" in result.warning.lower()


@pytest.mark.asyncio
async def test_maps_supported_model_output_to_suggestion(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        visual_recognition_service,
        "_post_json",
        lambda payload: {
            "output_text": json.dumps(
                {
                    "threat_code": "ghost_gear",
                    "confidence": 0.87,
                }
            )
        },
    )

    result = await (
        visual_recognition_service.recognize_visual_threat(
            content=b"image",
            content_type="image/jpeg",
        )
    )

    assert result.status == "recognized"
    assert result.suggested_threat.code == "ghost_gear"
    assert result.suggested_threat.label == (
        "Ghost fishing gear"
    )
    assert result.confidence == 0.87
    assert result.warning is None


@pytest.mark.asyncio
async def test_unsupported_or_uncertain_output_is_unsure(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        visual_recognition_service,
        "_post_json",
        lambda payload: {
            "output_text": json.dumps(
                {
                    "threat_code": "crown_of_thorns",
                    "confidence": 0.91,
                }
            )
        },
    )

    result = await (
        visual_recognition_service.recognize_visual_threat(
            content=b"image",
            content_type="image/png",
        )
    )

    assert result.status == "unsure"
    assert result.suggested_threat.code == "unsure"
    assert result.confidence is None
    assert "could not be matched" in result.warning


@pytest.mark.asyncio
async def test_invalid_provider_output_is_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "gemini_api_key",
        SecretStr("test-key"),
    )
    monkeypatch.setattr(
        visual_recognition_service,
        "_post_json",
        lambda payload: {"output_text": "not-json"},
    )

    result = await (
        visual_recognition_service.recognize_visual_threat(
            content=b"image",
            content_type="image/webp",
        )
    )

    assert result.status == "unavailable"
    assert result.suggested_threat is None
    assert result.confidence is None


def test_provider_payload_contains_inline_image_only():
    payload = visual_recognition_service._provider_payload(
        content=b"reef-image",
        content_type="image/png",
    )

    assert payload["model"] == "gemini-3.1-flash-lite"
    assert payload["input"][1] == {
        "type": "image",
        "data": base64.b64encode(
            b"reef-image"
        ).decode("ascii"),
        "mime_type": "image/png",
    }
    encoded = json.dumps(payload).lower()
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "location" in encoded
    assert "observer" in encoded


def test_posts_to_existing_gemini_interactions_endpoint(
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

    result = visual_recognition_service._post_json(
        visual_recognition_service._provider_payload(
            content=b"image",
            content_type="image/jpeg",
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
