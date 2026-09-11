from datetime import (
    datetime,
    timezone,
)

from pydantic import (
    Field,
    model_validator,
)

from app.core.enums import (
    CaseStatus,
    LocationSource,
)
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

    I2 explicit sources:
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

    # Existing I1 field.
    # Retained for backward compatibility.
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
        """
        Validate which coordinate representation may
        accompany each provenance source.

        Final location/confidence validation remains in
        location_service.py.
        """

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

    Fields are optional because the purpose of this
    endpoint is to identify an incomplete draft rather
    than reject it before evaluation.
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

    # Optional I2 metadata for uploaded evidence.
    #
    # Backward compatibility:
    # an empty list means the old I1 request contract still
    # works and captured_at will be stored as NULL.
    evidence_metadata: list[
        EvidenceMetadataInput
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
    items: list[
        ObserverReportSummary
    ]

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

    estimated_depth_metres: (
        float | None
    ) = None

    general_location: str
    dive_site: str | None = None

    precise_location: (
        ObserverLocationResponse | None
    ) = None

    status: CaseStatus
    status_label: str

    outcome: str | None = None

    information_request_reason: (
        str | None
    ) = None

    closure: (
        ObserverClosureSummary | None
    ) = None

    submitted_at: datetime


class ObserverTimelineEvent(APIModel):
    status_label: str
    occurred_at: datetime


class ObserverTimelineResponse(APIModel):
    report_reference: str

    timeline: list[
        ObserverTimelineEvent
    ]


class OpenInformationRequest(APIModel):
    """
    The request an observer still has to answer.
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
    Confirmation that the answer reached the existing
    case.
    """

    report_reference: str
    status: CaseStatus
    response_text: str
    responded_at: datetime

    coordinator_retained: (
        int | None
    ) = None