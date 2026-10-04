from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


VisualRecognitionStatus = Literal[
    "recognized",
    "unsure",
    "unavailable",
]

VisualThreatCode = Literal[
    "coral_bleaching",
    "ghost_gear",
    "marine_debris",
    "physical_reef_damage",
    "unsure",
]


class VisualThreatSuggestion(APIModel):
    code: VisualThreatCode
    label: str = Field(
        min_length=1,
        max_length=80,
    )


class VisualRecognitionResponse(APIModel):
    """
    Advisory image classification returned before report
    submission.

    The Observer's confirmed threat category remains the
    canonical report value.
    """

    status: VisualRecognitionStatus
    suggested_threat: VisualThreatSuggestion | None
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    warning: str | None = Field(
        default=None,
        max_length=300,
    )
