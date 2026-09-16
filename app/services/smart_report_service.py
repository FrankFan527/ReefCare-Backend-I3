import asyncio
import json
from urllib import error, request

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.schemas.smart_report import (
    SmartReportFollowUpQuestion,
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


_FOLLOW_UP_TEMPLATES = {
    "ghost fishing gear": (
        {
            "field": "approximate_size",
            "question": (
                "About how large was the net or gear?"
            ),
            "options": [
                "<1 m",
                "1-5 m",
                "5-10 m",
                ">10 m",
                "Unsure",
            ],
        },
        {
            "field": "animal_interaction",
            "question": (
                "Did you see any marine animals trapped "
                "in or interacting with it?"
            ),
            "options": ["Yes", "No", "Unsure"],
        },
    ),
    "coral bleaching": (
        {
            "field": "approximate_size",
            "question": (
                "How much coral appeared pale or white?"
            ),
            "options": [
                "Small patch",
                "Several colonies",
                "Widespread",
                "Unsure",
            ],
        },
    ),
    "marine debris": (
        {
            "field": "coral_interaction",
            "question": (
                "Was the debris touching or caught "
                "on coral?"
            ),
            "options": ["Yes", "No", "Unsure"],
        },
    ),
    "physical reef damage": (
        {
            "field": "coral_interaction",
            "question": "What did the damage look like?",
            "options": [
                "Broken coral",
                "Anchor or rope damage",
                "Collision damage",
                "Other or unsure",
            ],
        },
    ),
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
            "are advisory and require Observer confirmation. "
            "Return null instead of 'not specified' for any "
            "value that is not explicitly supported. Do not "
            "create follow-up questions; ReefCare selects a "
            "small predefined question set after extraction."
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

    follow_up_questions = (
        _select_follow_up_questions(model_output)
    )

    return SmartReportStructureResponse(
        available=True,
        suggestions=suggestions,
        missing_information=missing,
        follow_up_questions=follow_up_questions,
        requires_user_confirmation=True,
        message=(
            "Review every AI suggestion before continuing."
        ),
    )


def _normalise_threat(value: str | None) -> str | None:
    if value is None:
        return None

    normalised = " ".join(
        "".join(
            character
            if character.isalnum()
            else " "
            for character in value.lower()
        ).split()
    )
    aliases = {
        "ghost gear": "ghost fishing gear",
        "fishing gear": "ghost fishing gear",
        "bleaching": "coral bleaching",
        "debris": "marine debris",
        "reef damage": "physical reef damage",
        "physical damage": "physical reef damage",
    }
    canonical = aliases.get(normalised, normalised)
    return (
        canonical
        if canonical in _FOLLOW_UP_TEMPLATES
        else None
    )


def _select_follow_up_questions(
    model_output: _StructuredModelOutput,
) -> list[SmartReportFollowUpQuestion]:
    """
    Return no more than two high-value clarifications.

    Gemini's null structured values identify what is absent.
    ReefCare then chooses wording and answer choices from a
    controlled set associated with the likely threat.
    """

    threat = _normalise_threat(
        model_output.possible_threat
    )
    if threat is None:
        return []

    questions: list[SmartReportFollowUpQuestion] = []
    for template in _FOLLOW_UP_TEMPLATES[threat]:
        field = template["field"]
        if getattr(model_output, field) is not None:
            continue
        questions.append(
            SmartReportFollowUpQuestion(
                field=field,
                question=template["question"],
                options=template["options"],
            )
        )
        if len(questions) == 2:
            break

    return questions


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
