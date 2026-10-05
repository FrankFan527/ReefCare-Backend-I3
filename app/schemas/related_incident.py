# ---------------------------------------------------------------------------
# US5.9 Related Incident Detection — contracts.
#
# Two groups of models live here, deliberately kept apart:
#
#   1. ENGINE CONTRACT (plain dataclasses, never serialised to a client)
#      What HongShen's detection engine receives and returns. The engine reads
#      facts and writes results only through related_incident_repository.py,
#      so these shapes are the whole boundary between the engine and the case
#      workflow.
#
#   2. COORDINATOR API (APIModel, camelCase JSON)
#      What Yoosuf's Potentially Related Reports UI receives. Candidates carry
#      a reference, a relatedness level, short signals and an ownership state
#      only (US5.9 AC3). Descriptions, evidence and coordinates appear only in
#      the side-by-side comparison, which needs both reports owned (AC6).
#
# Vocabularies are kept in this module rather than app/core/enums.py so the
# I3 change stays additive to shared files. They can move later if Frank
# prefers one enums module.
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import Field, model_validator

from app.schemas.common import APIModel


# ---------------------------------------------------------------------------
# Vocabularies. Values match the CHECK constraints and reference rows in
# i3_e5_related_incidents.sql.
# ---------------------------------------------------------------------------

class DetectionRunState(str, Enum):
    """
    Stored state of one detection run (related_incident_run.run_state).
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    FAILED = "failed"


class RelatedAnalysisState(str, Enum):
    """
    What the Coordinator is told about the analysis (US5.9 AC3).

    This is derived, not stored. UNAVAILABLE covers a failed run, a stale
    processing run and a report that was never analysed, and must never be
    rendered as "no related reports" (AC9).
    """

    PROCESSING = "processing"
    MATCHES_AVAILABLE = "matches_available"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    NO_AVAILABLE_MATCHES = "no_available_matches"
    UNAVAILABLE = "unavailable"


class RelatednessLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ImageAnalysisState(str, Enum):
    NOT_ANALYSED = "not_analysed"
    DISABLED = "disabled"
    NO_SOURCE_IMAGES = "no_source_images"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_HISTORY = "insufficient_history"
    PARTIAL = "partial"
    READY = "ready"


class CandidateOwnershipState(str, Enum):
    """
    Only these two are ever shown (AC4). A candidate owned by another
    Coordinator is filtered out before the response is built.
    """

    UNCLAIMED = "unclaimed"
    OWNED_BY_YOU = "owned_by_you"


class RelationshipDecision(str, Enum):
    SAME_INCIDENT = "same_incident"
    NOT_RELATED = "not_related"


class CandidateDecisionState(str, Enum):
    """
    The latest human decision on the pair, as the Coordinator sees it.
    """

    UNDECIDED = "undecided"
    LINKED = "linked"
    NOT_RELATED = "not_related"


# ---------------------------------------------------------------------------
# 1. ENGINE CONTRACT
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageEmbedding:
    """Internal only: compatible, normalised vision features, never API data."""

    evidence_id: int
    vector: tuple[float, ...]
    model: str
    version: str


@dataclass(frozen=True)
class ReportComparisonFacts:
    """
    The eligible facts of one report, as handed to the detection engine.

    Location is generalised to 3 decimal places (about 110 m) here, in the
    repository, so the engine never holds a precise report coordinate.

    description is for internal comparison only. It must never be copied
    into a signal detail, a log line or any API response.

    Any field can be None. A missing value is not a match (US5.9 AC2).
    """

    report_id: int
    report_reference: str
    observed_at: datetime | None
    threat_category_code: str | None

    dive_site_id: int | None = None
    dive_site_name: str | None = None
    public_area_label: str | None = None

    generalised_latitude: Decimal | None = None
    generalised_longitude: Decimal | None = None
    location_confidence_code: str | None = None
    location_source_code: str | None = None

    estimated_depth_metres: Decimal | None = None
    description: str | None = None
    image_embeddings: tuple[ImageEmbedding, ...] = ()


@dataclass(frozen=True)
class CandidateSignal:
    """
    One explainable reason two reports look related.

    code must exist in similarity_signal.code. detail is a short factual
    qualifier such as "within 2 days" (max 160 chars), never report text.
    """

    code: str
    detail: str | None = None
    signal_score: Decimal | None = None
    signal_weight: Decimal | None = None


@dataclass(frozen=True)
class CandidateMatch:
    """
    One potential match produced by the engine.
    """

    candidate_report_id: int
    relatedness_level: RelatednessLevel
    signals: list[CandidateSignal]
    similarity_score: Decimal | None = None


@dataclass
class DetectionOutcome:
    """
    What the engine returns for one source report.

    run_state is COMPLETED (candidates may be empty) or
    INSUFFICIENT_INFORMATION. FAILED is set by the orchestration wrapper,
    not by the engine itself.
    """

    run_state: DetectionRunState
    candidates: list[CandidateMatch] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 2. COORDINATOR API
# ---------------------------------------------------------------------------

class RelatedReportSignal(APIModel):
    code: str
    label: str

    detail: str | None = None
    signal_score: float | None = Field(default=None, ge=0, le=1)
    signal_weight: float | None = Field(default=None, ge=0, le=1)


class RelatedReportCandidate(APIModel):
    """
    One actionable candidate (AC3, AC4). No description, evidence or
    coordinates: those are only available after Claim and Compare.
    """

    candidate_report_reference: str
    relatedness_level: RelatednessLevel
    relatedness_score: float | None = Field(default=None, ge=0, le=1)

    signals: list[RelatedReportSignal] = Field(default_factory=list)

    ownership_state: CandidateOwnershipState
    decision_state: CandidateDecisionState

    # true when an earlier Not Related decision is being shown again because
    # new evidence arrived on either report after the decision (AC7)
    reopened_by_new_evidence: bool = False


class RelatedReportsResponse(APIModel):
    report_reference: str

    analysis_state: RelatedAnalysisState

    # a plain-language line the UI can show as-is for every state
    message: str

    rule_version: str | None = None
    input_version: int | None = None
    image_analysis_state: ImageAnalysisState = ImageAnalysisState.NOT_ANALYSED
    image_analysis_message: str = "Image analysis has not completed."
    analysed_at: datetime | None = None

    candidates: list[RelatedReportCandidate] = Field(default_factory=list)


class ComparisonEvidenceItem(APIModel):
    """
    Safe evidence metadata. The image itself streams through the existing
    authenticated evidence route; no storage key is ever returned.
    """

    evidence_id: int
    media_type: str
    captured_at: datetime | None = None


class ComparisonReportSide(APIModel):
    """
    One side of the side-by-side comparison. Only returned when the acting
    Coordinator owns this report (US1.3 AC2).
    """

    report_reference: str
    status_code: str
    status_label: str

    threat_category_code: str
    threat_category_label: str

    observed_at: datetime
    submitted_at: datetime

    dive_site_name: str | None = None
    public_area_label: str | None = None
    location_confidence_code: str | None = None

    estimated_depth_metres: Decimal | None = None
    description: str

    incident_reference: str | None = None

    evidence: list[ComparisonEvidenceItem] = Field(default_factory=list)


class LatestRelationshipDecision(APIModel):
    decision: RelationshipDecision

    rejection_reason_code: str | None = None
    rejection_reason_label: str | None = None

    incident_reference: str | None = None

    decided_by_name: str | None = None
    decided_at: datetime


class ReportComparisonResponse(APIModel):
    current: ComparisonReportSide
    candidate: ComparisonReportSide

    # signals from the latest run that suggested this pair, if any
    signals: list[RelatedReportSignal] = Field(default_factory=list)
    relatedness_level: RelatednessLevel | None = None
    relatedness_score: float | None = Field(default=None, ge=0, le=1)

    latest_decision: LatestRelationshipDecision | None = None


class RelationshipDecisionCreate(APIModel):
    """
    Confirm Same Incident or Not Related (AC6, AC7).

    rejection_reason_code is required for not_related and must be absent for
    same_incident. Whether the reason needs a note is checked by PostgreSQL,
    because that rule lives on the reason row.
    """

    decision: RelationshipDecision

    rejection_reason_code: str | None = Field(
        default=None,
        max_length=50,
    )

    note: str | None = Field(
        default=None,
        max_length=1000,
    )

    @model_validator(mode="after")
    def the_reason_matches_the_decision(self):
        if (
            self.decision == RelationshipDecision.NOT_RELATED
            and not (self.rejection_reason_code or "").strip()
        ):
            raise ValueError(
                "rejectionReasonCode is required when decision is not_related"
            )

        if (
            self.decision == RelationshipDecision.SAME_INCIDENT
            and self.rejection_reason_code is not None
        ):
            raise ValueError(
                "rejectionReasonCode must be omitted when decision is same_incident"
            )

        return self


class RelationshipDecisionResponse(APIModel):
    report_reference: str
    related_report_reference: str

    decision: RelationshipDecision

    incident_reference: str | None = None
    rejection_reason_code: str | None = None

    decided_by: int
    decided_at: datetime


class RejectionReasonOption(APIModel):
    code: str
    label: str
    requires_note: bool
