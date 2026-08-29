from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from app.core.enums import CaseStatus
from app.schemas.common import APIModel

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


class ObserverReportSummary(APIModel):
    report_reference: str
    threat_category: str
    general_location: str

    status: CaseStatus
    status_label: str

    outcome: str | None = None
    submitted_at: datetime


class ObserverReportListResponse(APIModel):
    items: list[ObserverReportSummary]

    page: int
    page_size: int
    total: int


class ObserverLocationResponse(APIModel):
    latitude: float | None = None
    longitude: float | None = None

    uncertainty_metres: int | None = None
    confidence_label: str | None = None
    source_label: str | None = None

    relocation_notes: str | None = None


class ObserverClosureSummary(APIModel):
    status: CaseStatus
    closure_label: str
    public_note: str | None = None


class ObserverReportDetailResponse(APIModel):
    report_reference: str
    threat_category: str

    description: str
    observed_at: datetime
    estimated_depth_metres: float | None = None

    general_location: str
    dive_site: str | None = None
    precise_location: ObserverLocationResponse | None = None

    status: CaseStatus
    status_label: str
    outcome: str | None = None

    information_request_reason: str | None = None
    closure: ObserverClosureSummary | None = None

    submitted_at: datetime


class ObserverTimelineEvent(APIModel):
    status_label: str
    occurred_at: datetime


class ObserverTimelineResponse(APIModel):
    report_reference: str
    timeline: list[ObserverTimelineEvent]