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
    message: str | None = Field(
        default=None,
        max_length=300,
    )
