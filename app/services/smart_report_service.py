import asyncio
import json
from urllib import error, request

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.schemas.smart_report import (
    SmartReportStructureResponse,
    SmartReportSuggestion,
)


class _StructuredModelOutput(BaseModel):
    possible_threat: str | None = Field(
        max_length=200,
    )
    estimated_depth_metres: str | None = Field(
        max_length=100,
    )
    approximate_size: str | None = Field(
        max_length=200,
    )
    coral_interaction: str | None = Field(
        max_length=500,
    )
    animal_interaction: str | None = Field(
        max_length=500,
    )
    site_reference: str | None = Field(
        max_length=300,
    )
    missing_information: list[str] = Field(
        max_length=6,
    )


_FIELD_LABELS = {
    "possible_threat": "Possible threat",
    "estimated_depth_metres": "Estimated depth",
    "approximate_size": "Approximate size",
    "coral_interaction": "Coral interaction",
    "animal_interaction": "Animal interaction",
    "site_reference": "Site reference",
}


_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "possible_threat": {
            "type": ["string", "null"],
        },
        "estimated_depth_metres": {
            "type": ["string", "null"],
        },
        "approximate_size": {
            "type": ["string", "null"],
        },
        "coral_interaction": {
            "type": ["string", "null"],
        },
        "animal_interaction": {
            "type": ["string", "null"],
        },
        "site_reference": {
            "type": ["string", "null"],
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
        },
    },
    "required": [
        "possible_threat",
        "estimated_depth_metres",
        "approximate_size",
        "coral_interaction",
        "animal_interaction",
        "site_reference",
        "missing_information",
    ],
}


def _provider_payload(description: str) -> dict:
    return {
        "model": settings.gemini_model,
        "system_instruction": (
            "You assist a Malaysian reef observer in "
            "structuring a report. Extract only details "
            "explicitly stated in the description. Never "
            "diagnose coral or wildlife, infer a precise "
            "location, or invent missing facts. A possible "
            "threat must be one of: coral bleaching, ghost "
            "fishing gear, marine debris, physical reef "
            "damage, or null when uncertain. Use concise, "
            "plain English. List useful missing information "
            "as questions or short labels. The suggestions "
            "are advisory and require Observer confirmation."
        ),
        "input": description,
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


def _extract_output_text(provider_response: dict) -> str:
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
    model_output: _StructuredModelOutput,
) -> SmartReportStructureResponse:
    values = model_output.model_dump(
        exclude={"missing_information"}
    )
    suggestions = []

    for field, label in _FIELD_LABELS.items():
        value = values[field]
        if field == "possible_threat" and value is None:
            value = "Not specified"
        if value is None:
            continue
        suggestions.append(
            SmartReportSuggestion(
                field=field,
                label=label,
                suggested_value=value.strip(),
            )
        )

    missing = []
    for item in model_output.missing_information:
        cleaned = item.strip()[:200]
        if cleaned and cleaned not in missing:
            missing.append(cleaned)

    return SmartReportStructureResponse(
        available=True,
        suggestions=suggestions,
        missing_information=missing,
        message=(
            "Review every AI suggestion before continuing."
        ),
    )


async def structure_report_description(
    description: str,
) -> SmartReportStructureResponse:
    if settings.gemini_api_key is None:
        return SmartReportStructureResponse(
            available=False,
            message=(
                "Smart Report Structuring is not "
                "configured. Continue the report manually."
            ),
        )

    try:
        provider_response = await asyncio.wait_for(
            asyncio.to_thread(
                _post_json,
                _provider_payload(description),
            ),
            timeout=(
                settings.smart_report_timeout_seconds + 1
            ),
        )
        output = _StructuredModelOutput.model_validate_json(
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
        return SmartReportStructureResponse(
            available=False,
            message=(
                "Smart Report Structuring is temporarily "
                "unavailable. Continue the report manually."
            ),
        )
