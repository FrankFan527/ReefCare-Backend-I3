from datetime import datetime, timezone

from pydantic import Field, model_validator

from app.core.enums import CaseStatus
from app.schemas.common import APIModel

class MapPinInput(APIModel):
    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )

class ObservationLocationInput(APIModel):
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

class ReportCreate(APIModel):
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

class ThreatCategoryResponse(APIModel):
    threat_category_id: int
    code: str
    label: str

    short_explanation: str | None = None
    useful_evidence: str | None = None
    safety_reminder: str | None = None
    icon_reference: str | None = None


class ReportSubmittedResponse(APIModel):
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




class OpenInformationRequest(APIModel):
    """
    The request an observer still has to answer.

    Carries the timestamp as well as the text. US6.3 AC5 asks for the relevant
    timestamp and acting user on every interaction, and the observer half of
    that is being able to see when they were asked.

    requested_by is deliberately absent. The observer has no need for the
    coordinator's user id, and the existing observer projections are careful
    never to expose coordinator identity.
    """

    request_text: str
    requested_at: datetime


class InformationResponseCreate(APIModel):
    """
    An observer's answer to an open information request.

    US6.3 AC2 allows text or optional evidence. This is the text path; photo
    attachment is a separate change, and evidence.case_event_id already exists
    in the database to carry it.
    """

    response_text: str = Field(
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def response_text_must_not_be_blank(self):
        """
        min_length alone accepts a string of spaces, which would record an
        empty answer as though the observer had responded and hand the
        coordinator nothing to re-review.
        """

        if self.response_text.strip() == "":
            raise ValueError("responseText must not be empty")

        return self


class InformationResponseAccepted(APIModel):
    """
    Confirmation that the answer reached the existing case.

    coordinator_retained is returned rather than assumed. US6.3 AC3 requires
    the same report and the same coordinator to survive the response, and
    returning the owner is how the frontend, and a test, can see that it did.
    """

    report_reference: str
    status: CaseStatus
    response_text: str
    responded_at: datetime

    coordinator_retained: int | None = None