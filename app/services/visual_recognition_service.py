import asyncio
import base64
import json
from urllib import error, request

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.schemas.visual_recognition import (
    VisualRecognitionResponse,
    VisualThreatSuggestion,
)


_THREAT_LABELS = {
    "coral_bleaching": "Coral bleaching",
    "ghost_gear": "Ghost fishing gear",
    "marine_debris": "Marine debris",
    "physical_reef_damage": "Physical reef damage",
}

_UNSURE_WARNING = (
    "The image could not be matched confidently to a "
    "supported threat category."
)

_UNAVAILABLE_WARNING = (
    "Visual recognition is temporarily unavailable. "
    "You can continue the report manually."
)


class _RecognitionModelOutput(BaseModel):
    threat_code: str | None = Field(
        default=None,
        max_length=80,
    )
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )


_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "threat_code": {
            "type": ["string", "null"],
        },
        "confidence": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
        },
    },
    "required": [
        "threat_code",
        "confidence",
    ],
    "additionalProperties": False,
}


def _provider_payload(
    *,
    content: bytes,
    content_type: str,
) -> dict:
    return {
        "model": settings.gemini_model,
        "system_instruction": (
            "You are a bounded visual classification aid "
            "for a Malaysian reef reporting workflow. "
            "Classify only visible evidence in the supplied "
            "image. Never diagnose, infer location, or add "
            "facts that are not visible. Return exactly one "
            "threat_code from coral_bleaching, ghost_gear, "
            "marine_debris, physical_reef_damage, or null. "
            "Use null with null confidence when the image is "
            "unclear, unrelated, or does not confidently "
            "match a supported category. Confidence must be "
            "between 0 and 1. The result is advisory and must "
            "be confirmed by the Observer."
        ),
        "input": [
            {
                "type": "text",
                "text": (
                    "Identify whether the image visibly "
                    "matches one supported reef threat."
                ),
            },
            {
                "type": "image",
                "data": base64.b64encode(
                    content
                ).decode("ascii"),
                "mime_type": content_type,
            },
        ],
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": _OUTPUT_SCHEMA,
        },
    }


def _post_json(payload: dict) -> dict:
    api_key = settings.gemini_api_key
    if api_key is None:
        raise RuntimeError("AI provider is not configured")

    endpoint = (
        settings.gemini_base_url.rstrip("/")
        + "/interactions"
    )
    encoded = json.dumps(payload).encode("utf-8")
    provider_request = request.Request(
        endpoint,
        data=encoded,
        method="POST",
        headers={
            "x-goog-api-key": api_key.get_secret_value(),
            "Content-Type": "application/json",
        },
    )

    with request.urlopen(
        provider_request,
        timeout=(
            settings.smart_report_timeout_seconds
        ),
    ) as provider_response:
        return json.loads(
            provider_response.read().decode("utf-8")
        )


def _extract_output_text(
    provider_response: dict,
) -> str:
    direct = provider_response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    for step in provider_response.get("steps", []):
        if (
            not isinstance(step, dict)
            or step.get("type") != "model_output"
        ):
            continue
        for content in step.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "text"
                and isinstance(content.get("text"), str)
            ):
                return content["text"]

    raise ValueError("AI provider returned no text output")


def _to_api_response(
    model_output: _RecognitionModelOutput,
) -> VisualRecognitionResponse:
    code = (
        model_output.threat_code
        .strip()
        .lower()
        if model_output.threat_code is not None
        else None
    )

    if (
        code not in _THREAT_LABELS
        or model_output.confidence is None
    ):
        return VisualRecognitionResponse(
            status="unsure",
            suggested_threat=VisualThreatSuggestion(
                code="unsure",
                label="Unsure",
            ),
            confidence=None,
            warning=_UNSURE_WARNING,
        )

    return VisualRecognitionResponse(
        status="recognized",
        suggested_threat=VisualThreatSuggestion(
            code=code,
            label=_THREAT_LABELS[code],
        ),
        confidence=model_output.confidence,
        warning=None,
    )


def _unavailable_response() -> VisualRecognitionResponse:
    return VisualRecognitionResponse(
        status="unavailable",
        suggested_threat=None,
        confidence=None,
        warning=_UNAVAILABLE_WARNING,
    )


async def recognize_visual_threat(
    *,
    content: bytes,
    content_type: str,
) -> VisualRecognitionResponse:
    """
    Classify a validated pre-submission image without
    storing the image or model output.

    Provider/configuration failures intentionally return a
    normal, non-blocking response so manual reporting can
    continue.
    """

    if settings.gemini_api_key is None:
        return _unavailable_response()

    try:
        provider_response = await asyncio.wait_for(
            asyncio.to_thread(
                _post_json,
                _provider_payload(
                    content=content,
                    content_type=content_type,
                ),
            ),
            timeout=(
                settings.smart_report_timeout_seconds + 1
            ),
        )
        output = _RecognitionModelOutput.model_validate_json(
            _extract_output_text(provider_response)
        )
        return _to_api_response(output)
    except (
        TimeoutError,
        error.HTTPError,
        error.URLError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        RuntimeError,
    ):
        return _unavailable_response()
