from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

class MapPinInput(BaseModel):
    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )

class ObservationLocationInput(BaseModel):
    named_dive_site_id: int = Field(
        gt=0
    )

    location_confidence: str = Field(
        min_length=1,
        max_length=50,
    )

    map_pin: MapPinInput | None = None

    relocation_notes: str | None = Field(
        default=None,
        max_length=1000,
    )

class ReportCreate(BaseModel):
    threat_category_id: int = Field(
        gt=0
    )

    observed_at: datetime

    estimated_depth_metres: float | None = Field(
        default=None,
        ge=0,
    )

    description: str = Field(
        min_length=1,
        max_length=4000,
    )

    dive_session_id: int = Field(
        gt=0
    )

    location: ObservationLocationInput

    @model_validator(mode="after")
    def validate_report_submission(self):
        if not self.description.strip():
            raise ValueError(
                "Description must not be empty"
            )

        observed_at = self.observed_at

        if observed_at.tzinfo is None:
            raise ValueError(
                "observed_at must include a timezone"
            )

        if observed_at > datetime.now(
            timezone.utc
        ):
            raise ValueError(
                "Observation time cannot be in the future"
            )

        return self

class ThreatCategoryResponse(BaseModel):
    threat_category_id: int
    code: str
    label: str

    short_explanation: str | None = None
    useful_evidence: str | None = None
    safety_reminder: str | None = None
    icon_reference: str | None = None


class ReportSubmittedResponse(BaseModel):
    report_reference: str
    status: str

    submitted_at: datetime

    general_location: str