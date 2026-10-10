from datetime import (
    date,
    datetime,
    timezone,
)
from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from app.core.enums import (
    CaseStatus,
    LocationSource,
)
from app.schemas.common import APIModel


# ---------------------------------------------------------------------------
# Shared report input models.
# ---------------------------------------------------------------------------


class MapPinInput(APIModel):
    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )


class EvidenceMetadataInput(APIModel):
    """
    Optional metadata for one uploaded evidence file.

    The order of evidenceMetadata corresponds to the order
    of the multipart photos array.

    captured_at is contextual information only.

    It must never silently change:
    - dive session
    - dive site
    - report location
    """

    captured_at: datetime | None = None

    @model_validator(mode="after")
    def validate_captured_at(
        self,
    ):
        if self.captured_at is None:
            return self

        if self.captured_at.tzinfo is None:
            raise ValueError(
                "capturedAt must include a timezone"
            )

        if self.captured_at > datetime.now(
            timezone.utc
        ):
            raise ValueError(
                "capturedAt cannot be in the future"
            )

        return self


# ---------------------------------------------------------------------------
# Report location.
# ---------------------------------------------------------------------------


class ObservationLocationInput(APIModel):
    """
    Observation location and provenance.

    named_dive_site_id remains required because the named
    site is the report's general/public-safe location.

    location_source records how any more precise location
    information was obtained.

    Backward compatibility:

    - no locationSource + mapPin -> manual_map_pin
    - no locationSource + no mapPin -> named_dive_site

    Supported sources:

    - named_dive_site
    - manual_map_pin
    - entered_coordinates
    - device_metadata
    - unknown
    """

    named_dive_site_id: int = Field(
        gt=0,
    )

    location_confidence: str = Field(
        min_length=1,
        max_length=50,
    )

    location_source: (
        LocationSource | None
    ) = None

    # Existing I1 field retained for compatibility.
    map_pin: MapPinInput | None = None

    # Used for manually entered coordinates or coordinates
    # obtained from device/photo metadata.
    coordinates: MapPinInput | None = None

    relocation_notes: str | None = Field(
        default=None,
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_location_source_shape(
        self,
    ):
        source = self.location_source

        # I1 compatibility.
        if source is None:
            if self.map_pin is not None:
                source = (
                    LocationSource
                    .MANUAL_MAP_PIN
                )
            else:
                source = (
                    LocationSource
                    .NAMED_DIVE_SITE
                )

        if (
            source
            == LocationSource.MANUAL_MAP_PIN
        ):
            if self.map_pin is None:
                raise ValueError(
                    "mapPin is required when "
                    "locationSource is "
                    "manual_map_pin"
                )

            if self.coordinates is not None:
                raise ValueError(
                    "coordinates must not be supplied "
                    "with manual_map_pin; use mapPin"
                )

        elif source in {
            LocationSource.ENTERED_COORDINATES,
            LocationSource.DEVICE_METADATA,
        }:
            if self.coordinates is None:
                raise ValueError(
                    "coordinates are required when "
                    f"locationSource is {source.value}"
                )

            if self.map_pin is not None:
                raise ValueError(
                    "mapPin must not be supplied for "
                    f"{source.value}"
                )

        elif source in {
            LocationSource.NAMED_DIVE_SITE,
            LocationSource.UNKNOWN,
        }:
            if (
                self.map_pin is not None
                or self.coordinates is not None
            ):
                raise ValueError(
                    f"{source.value} must not include "
                    "report-specific coordinates"
                )

        return self


class ReportCompletenessLocationInput(
    APIModel
):
    """
    Relaxed location representation used only for the
    completeness checker.

    Fields are optional because this endpoint identifies
    incomplete draft content rather than rejecting the
    draft before evaluation.
    """

    named_dive_site_id: (
        int | None
    ) = Field(
        default=None,
        gt=0,
    )

    location_confidence: (
        str | None
    ) = Field(
        default=None,
        max_length=50,
    )

    location_source: (
        LocationSource | None
    ) = None

    map_pin: (
        MapPinInput | None
    ) = None

    coordinates: (
        MapPinInput | None
    ) = None

    relocation_notes: (
        str | None
    ) = Field(
        default=None,
        max_length=1000,
    )


# ---------------------------------------------------------------------------
# Completeness checking.
# ---------------------------------------------------------------------------


class ReportCompletenessRequest(
    APIModel
):
    """
    Permissive representation of an unfinished report.

    Unlike ReportCreate, required fields are optional here
    because this endpoint must be able to report which
    fields are still missing.
    """

    threat_category_id: (
        int | None
    ) = Field(
        default=None,
        gt=0,
    )

    observed_at: (
        datetime | None
    ) = None

    estimated_depth_metres: (
        float | None
    ) = Field(
        default=None,
        ge=0,
    )

    description: (
        str | None
    ) = Field(
        default=None,
        max_length=4000,
    )

    dive_session_id: (
        int | None
    ) = Field(
        default=None,
        gt=0,
    )

    location: (
        ReportCompletenessLocationInput
        | None
    ) = None

    evidence_count: int = Field(
        default=0,
        ge=0,
    )


class ReportCompletenessResponse(
    APIModel
):
    """
    Deterministic readiness result for a report draft.

    blocking_missing:
        required information that has not been supplied

    blocking_issues:
        information that was supplied but is invalid or
        inconsistent

    recommended_missing:
        useful information that does not block submission
    """

    is_submittable: bool

    blocking_missing: list[str]
    blocking_issues: list[str]

    recommended_missing: list[str]

    summary: str


# ---------------------------------------------------------------------------
# Iteration 3 — E4 AI suggestion provenance and review.
#
# Smart Report Structuring and Visual Threat Recognition
# are independent advisory sources.
#
# The Observer's final report fields remain authoritative.
# ---------------------------------------------------------------------------


AISuggestionSource = Literal[
    "smart_report",
    "visual_recognition",
]


AISuggestionStatus = Literal[
    "unresolved",
    "confirmed",
    "corrected",
    "removed",
]


class AISuggestionState(APIModel):
    """
    Observer-side resolution state for one AI suggestion.

    I3 supports two independent advisory sources:

    - smart_report
    - visual_recognition

    AI output is never authoritative.

    unresolved may exist during final review, but it must
    not be persisted as a completed report suggestion.
    """

    field: str = Field(
        min_length=1,
        max_length=100,
    )

    source: AISuggestionSource

    suggested_value: (
        str | None
    ) = Field(
        default=None,
        max_length=500,
    )

    confidence: (
        float | None
    ) = Field(
        default=None,
        ge=0,
        le=1,
    )

    status: AISuggestionStatus

    @model_validator(mode="after")
    def validate_source_specific_shape(
        self,
    ):
        """
        Smart Report Structuring currently does not expose
        a comparable numeric confidence score.

        Visual Recognition may provide confidence in the
        range 0..1.

        Keeping Smart Report confidence null prevents the
        API from implying precision the source never
        supplied.
        """

        if (
            self.source
            == "smart_report"
            and self.confidence is not None
        ):
            raise ValueError(
                "confidence must be null for "
                "smart_report suggestions"
            )

        return self


class AIConflictResponse(APIModel):
    """
    One disagreement between Smart Report Structuring and
    Visual Threat Recognition for the same report field.

    This is advisory only.

    The conflict never selects or overwrites the Observer's
    final report value.
    """

    field: str = Field(
        min_length=1,
        max_length=100,
    )

    text_suggestion: (
        str | None
    ) = Field(
        default=None,
        max_length=500,
    )

    visual_suggestion: (
        str | None
    ) = Field(
        default=None,
        max_length=500,
    )

    visual_confidence: (
        float | None
    ) = Field(
        default=None,
        ge=0,
        le=1,
    )


class AIReviewSummary(APIModel):
    """
    Final-review summary of agreement or disagreement
    between AI sources.

    has_conflict indicates that two supported AI sources
    produced different suggestions for the same field.

    A conflict is informational and must still be resolved
    explicitly by the Observer.
    """

    has_conflict: bool = False

    conflicts: list[
        AIConflictResponse
    ] = Field(
        default_factory=list,
    )


# ---------------------------------------------------------------------------
# Final report review.
# ---------------------------------------------------------------------------


class ReportReviewRequest(
    ReportCompletenessRequest
):
    """
    Final non-persistent Observer review input.

    This model intentionally extends the permissive
    completeness request so review can still explain why a
    draft is not ready.

    evidence_count describes how many evidence items will
    be submitted.

    evidence_metadata carries optional capturedAt values.

    ai_suggestions contains the current Observer resolution
    state for both supported advisory AI sources.
    """

    evidence_metadata: list[
        EvidenceMetadataInput
    ] = Field(
        default_factory=list,
    )

    ai_suggestions: list[
        AISuggestionState
    ] = Field(
        default_factory=list,
    )


class ReportReviewSummary(APIModel):
    threat: dict | None = None

    observed_at: datetime | None = None

    estimated_depth_metres: (
        float | None
    ) = None

    description: str | None = None

    dive_session: dict | None = None
    dive_site: dict | None = None

    location_source: (
        LocationSource | None
    ) = None

    location_confidence: (
        str | None
    ) = None


# ---------------------------------------------------------------------------
# Advisory selected-site versus precise-location check.
# ---------------------------------------------------------------------------


class LocationCheckRequest(APIModel):
    """
    Advisory consistency check between a selected named
    dive site and an optional precise observation point.

    This check never modifies or blocks submission.
    """

    named_dive_site_id: int = Field(
        gt=0,
    )

    location_source: LocationSource

    map_pin: (
        MapPinInput | None
    ) = None

    coordinates: (
        MapPinInput | None
    ) = None

    @model_validator(mode="after")
    def validate_location_shape(
        self,
    ):
        if (
            self.location_source
            == LocationSource.MANUAL_MAP_PIN
        ):
            if self.map_pin is None:
                raise ValueError(
                    "mapPin is required when "
                    "locationSource is manual_map_pin"
                )

            if self.coordinates is not None:
                raise ValueError(
                    "coordinates must not be supplied "
                    "with manual_map_pin"
                )

        elif self.location_source in {
            LocationSource.ENTERED_COORDINATES,
            LocationSource.DEVICE_METADATA,
        }:
            if self.coordinates is None:
                raise ValueError(
                    "coordinates are required when "
                    f"locationSource is "
                    f"{self.location_source.value}"
                )

            if self.map_pin is not None:
                raise ValueError(
                    "mapPin must not be supplied for "
                    f"{self.location_source.value}"
                )

        elif self.location_source in {
            LocationSource.NAMED_DIVE_SITE,
            LocationSource.UNKNOWN,
        }:
            if (
                self.map_pin is not None
                or self.coordinates is not None
            ):
                raise ValueError(
                    f"{self.location_source.value} "
                    "must not contain precise coordinates"
                )

        return self


class LocationCheckResponse(APIModel):
    """
    Advisory site-to-point consistency result.

    check_available becomes false when the selected site
    does not have a usable reference centre coordinate.

    A warning never blocks submission.
    """

    check_available: bool
    has_warning: bool

    warning_code: (
        str | None
    ) = None

    message: (
        str | None
    ) = None

    distance_metres: (
        int | None
    ) = None

    threshold_metres: (
        int | None
    ) = None

    selected_site_id: int

    selected_site_name: (
        str | None
    ) = None


class ReportReviewResponse(APIModel):
    """
    Aggregated Observer review result before final report
    submission.

    I3 exposes AI-source disagreement explicitly.

    AI conflict information is advisory and must never
    replace the Observer-confirmed report value.
    """

    is_submittable: bool

    completeness: (
        ReportCompletenessResponse
    )

    unresolved_suggestions: list[
        AISuggestionState
    ]

    ai_review: AIReviewSummary = Field(
        default_factory=AIReviewSummary,
    )

    report: ReportReviewSummary

    evidence: list[dict]

    location_warning: (
        LocationCheckResponse | None
    ) = None


# ---------------------------------------------------------------------------
# Final report submission.
# ---------------------------------------------------------------------------


class ReportCreate(APIModel):
    threat_category_id: int = Field(
        gt=0,
    )

    observed_at: datetime

    estimated_depth_metres: (
        float | None
    ) = Field(
        default=None,
        ge=0,
    )

    description: str = Field(
        min_length=1,
        max_length=4000,
    )

    dive_session_id: int = Field(
        gt=0,
    )

    location: ObservationLocationInput

    evidence_metadata: list[
        EvidenceMetadataInput
    ] = Field(
        default_factory=list,
    )

    ai_suggestions: list[
        AISuggestionState
    ] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_report_submission(
        self,
    ):
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
                "Observation time cannot be "
                "in the future"
            )

        unresolved_suggestions = [
            suggestion
            for suggestion
            in self.ai_suggestions
            if (
                suggestion.status
                == "unresolved"
            )
        ]

        if unresolved_suggestions:
            raise ValueError(
                "All AI suggestions must be confirmed, "
                "corrected or removed before submission"
            )

        return self


# ---------------------------------------------------------------------------
# Reference / submission confirmation.
# ---------------------------------------------------------------------------


class ThreatCategoryResponse(APIModel):
    threat_category_id: int
    code: str
    label: str

    short_explanation: (
        str | None
    ) = None

    useful_evidence: (
        str | None
    ) = None

    safety_reminder: (
        str | None
    ) = None

    source_reference: (
        str | None
    ) = None

    last_reviewed_at: (
        date | None
    ) = None

    icon_reference: (
        str | None
    ) = None


class ReportSubmittedResponse(APIModel):
    """
    Confirmation that a report was successfully submitted.
    """

    report_reference: str
    status: str

    submitted_at: datetime

    general_location: str


# ---------------------------------------------------------------------------
# Observer tracking projections.
# ---------------------------------------------------------------------------


class ObserverReportSummary(APIModel):
    """
    One Observer-safe item in My Reports.
    """

    report_reference: str
    threat_category: str
    general_location: str

    dive_site: (
        str | None
    ) = None

    observed_at: datetime

    status: CaseStatus
    status_label: str

    outcome: (
        str | None
    ) = None

    needs_attention: bool = False

    submitted_at: datetime

    last_updated_at: datetime


class ObserverReportListResponse(APIModel):
    items: list[
        ObserverReportSummary
    ]

    page: int
    page_size: int
    total: int


class ObserverLocationResponse(APIModel):
    latitude: (
        float | None
    ) = None

    longitude: (
        float | None
    ) = None

    uncertainty_metres: (
        int | None
    ) = None

    confidence_label: (
        str | None
    ) = None

    source_label: (
        str | None
    ) = None

    relocation_notes: (
        str | None
    ) = None


class ObserverClosureSummary(APIModel):
    status: CaseStatus

    closure_label: str

    public_note: (
        str | None
    ) = None


# ---------------------------------------------------------------------------
# Iteration 3 — E6 Observer Impact Feedback.
# ---------------------------------------------------------------------------


class ObserverContributionSummary(APIModel):
    """
    Observer-safe explanation of how the report has
    contributed to ReefCare follow-up.

    This object is built only from already-recorded E5/E7
    facts.

    It must never:
    - invent conservation activity
    - expose Coordinator identity
    - expose internal case notes
    - expose private report/evidence data
    - describe a planned action as completed
    """

    contribution_type: str

    state: str

    label: str

    detail: (
        str | None
    ) = None

    recorded_at: (
        datetime | None
    ) = None

    next_follow_up_required: bool = False

    next_follow_up_date: (
        date | None
    ) = None


class ObserverReportDetailResponse(APIModel):
    """
    Observer-safe detailed tracking view.

    Iteration 3 adds an optional contribution summary
    derived from already-recorded E5/E7 state while
    preserving the existing privacy boundary.
    """

    report_reference: str
    threat_category: str

    description: str
    observed_at: datetime

    estimated_depth_metres: (
        float | None
    ) = None

    general_location: str

    dive_site: (
        str | None
    ) = None

    precise_location: (
        ObserverLocationResponse | None
    ) = None

    evidence_count: int = 0

    status: CaseStatus
    status_label: str

    outcome: (
        str | None
    ) = None

    contribution: (
        ObserverContributionSummary
        | None
    ) = None

    needs_attention: bool = False

    information_request_reason: (
        str | None
    ) = None

    closure: (
        ObserverClosureSummary | None
    ) = None

    submitted_at: datetime

    last_updated_at: datetime


class ObserverTimelineEvent(APIModel):
    """
    One Observer-safe timeline event.

    event_type distinguishes ordinary workflow states from
    Iteration 3 impact events.

    Expected values include:
    - status
    - related_incident
    - follow_up

    The event contains no private actor identity, internal
    incident id, related report reference or private notes.
    """

    event_type: str = "status"

    status_label: str

    occurred_at: datetime

    is_current: bool = False


class ObserverTimelineResponse(APIModel):
    """
    Observer-safe report timeline plus explicit current
    state.

    current_status is the canonical code needed by the
    frontend for deterministic behaviour.

    current_status_label is the public/Observer wording.
    """

    report_reference: str

    current_status: CaseStatus
    current_status_label: str

    timeline: list[
        ObserverTimelineEvent
    ]


# ---------------------------------------------------------------------------
# Observer response to Coordinator information request.
# ---------------------------------------------------------------------------


class OpenInformationRequest(APIModel):
    """
    The request an observer still has to answer.

    requested_by is deliberately absent so Coordinator
    identity is not exposed to the Observer.
    """

    request_text: str

    requested_at: datetime


class InformationResponseCreate(APIModel):
    """
    An observer's answer to an open information request.
    """

    response_text: str = Field(
        min_length=1,
        max_length=2000,
    )

    @model_validator(mode="after")
    def response_text_must_not_be_blank(
        self,
    ):
        if self.response_text.strip() == "":
            raise ValueError(
                "responseText must not be empty"
            )

        return self


class InformationResponseAccepted(APIModel):
    """
    Confirmation that the answer reached the existing case.
    """

    report_reference: str

    status: CaseStatus

    response_text: str

    responded_at: datetime

    coordinator_retained: (
        int | None
    ) = None


# ---------------------------------------------------------------------------
# US6.3 — observer reply with photos (QA, Rifdhan 10 Oct).
#
# Sent as multipart: responseText plus up to five photos in `photos`. The
# JSON-only information-response route above stays exactly as it was.
# ---------------------------------------------------------------------------

# a reply answers one question, so it carries a handful of photos at most
MAX_INFORMATION_RESPONSE_PHOTOS: int = 5


class InformationResponseEvidence(APIModel):
    """
    Safe metadata for one photo sent with a reply. The private storage key is
    never returned.
    """

    evidence_id: int

    media_type: str

    file_size_bytes: (
        int | None
    ) = None

    uploaded_at: datetime


class InformationResponseWithPhotosAccepted(
    InformationResponseAccepted
):
    """
    Confirmation that the answer and its photos reached the existing case,
    under the same coordinator. caseEventId is the reply's history event,
    which every photo here is linked to.
    """

    case_event_id: int

    evidence: list[
        InformationResponseEvidence
    ] = Field(
        default_factory=list
    )
