from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


SmartReportField = Literal[
    "possible_threat",
    "estimated_depth_metres",
    "approximate_size",
    "coral_interaction",
    "animal_interaction",
    "site_reference",
]


class SmartReportStructureRequest(APIModel):
    description: str = Field(
        min_length=10,
        max_length=4000,
    )


class SmartReportSuggestion(APIModel):
    field: SmartReportField
    label: str = Field(
        min_length=1,
        max_length=80,
    )
    suggested_value: str | None = Field(
        default=None,
        max_length=500,
    )


class SmartReportFollowUpQuestion(APIModel):
    """
    One bounded, predefined clarification question.

    Gemini identifies which supported values are absent;
    ReefCare owns the wording and permitted answers so this
    never becomes an unrestricted AI conversation.
    """

    field: SmartReportField
    question: str = Field(
        min_length=1,
        max_length=240,
    )
    options: list[str] = Field(
        min_length=2,
        max_length=5,
    )


class SmartReportStructureResponse(APIModel):
    available: bool
    suggestions: list[SmartReportSuggestion] = Field(
        default_factory=list,
        max_length=6,
    )
    missing_information: list[str] = Field(
        default_factory=list,
        max_length=6,
    )
    follow_up_questions: list[
        SmartReportFollowUpQuestion
    ] = Field(
        default_factory=list,
        max_length=2,
    )
    requires_user_confirmation: bool = True
    message: str | None = Field(
        default=None,
        max_length=300,
    )
