from datetime import datetime
from enum import Enum

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from app.core.enums import CaseStatus
from app.schemas.common import APIModel


class EvidenceCompleteness(
    str,
    Enum,
):
    """
    US5.1 evidence-completeness indicator.

    This is computed on read and is not a PostgreSQL
    persisted vocabulary.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    MINIMAL = "minimal"


class CasePriority(
    str,
    Enum,
):
    """
    US5.7 priority cue.

    This is guidance only and does not verify the threat or
    mutate the workflow.
    """

    HIGH = "high"
    MEDIUM = "medium"
    STANDARD = "standard"


class CaseOwnerResponse(APIModel):
    id: int
    display_name: str


class CoordinatorQueueItem(APIModel):
    """
    Queue-safe representation of one active submitted
    report.

    Precise coordinates and private evidence are excluded.
    """

    report_reference: str

    threat: str

    area: (
        str | None
    ) = None

    status_code: CaseStatus
    status_label: str

    submitted_at: datetime
    hours_in_queue: int

    evidence_completeness: (
        EvidenceCompleteness
    )

    evidence_count: int

    priority: CasePriority

    priority_reasons: list[
        str
    ]

    owner: (
        CaseOwnerResponse | None
    ) = None

    claimed_at: (
        datetime | None
    ) = None


class CoordinatorQueueResponse(APIModel):
    items: list[
        CoordinatorQueueItem
    ]

    page: int
    page_size: int
    total: int


class ClaimedCaseResponse(APIModel):
    report_reference: str

    owner: CaseOwnerResponse

    status_code: CaseStatus
    status_label: str

    claimed_at: datetime


class StartReviewResponse(APIModel):
    """
    Confirmation that an owned claimed case has entered
    coordinator review.
    """

    report_reference: str
    status_code: CaseStatus


class PreciseLocationResponse(APIModel):
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


class EvidenceSummary(APIModel):
    evidence_id: int
    media_type: str

    captured_at: (
        datetime | None
    ) = None

    uploaded_at: datetime


class LatestDecisionResponse(APIModel):
    """
    Latest persisted US5.4 response decision.

    Evidence-assessment and terminal-closure-only rows are
    excluded by the repository.
    """

    response_type: str

    notes: (
        str | None
    ) = None

    referred_to: (
        str | None
    ) = None

    decided_at: datetime


class CaseTriageContext(APIModel):
    """
    Queue/case-detail triage information produced from the
    same deterministic backend rules.
    """

    evidence_completeness: (
        EvidenceCompleteness
    )

    evidence_count: int

    priority: CasePriority

    priority_reasons: list[
        str
    ]

    hours_in_queue: int


class AIAssistedContext(APIModel):
    """
    AI output remains structurally separate from Observer
    statements and Coordinator decisions.
    """

    triage_brief: (
        str | None
    ) = None

    generated_at: (
        datetime | None
    ) = None

    is_unverified_ai_output: (
        bool
    ) = True


class InformationExchangeEntry(APIModel):
    """
    One information-request/response interaction.
    """

    event_type: str

    message: (
        str | None
    ) = None

    occurred_at: datetime

    actor_user_id: (
        int | None
    ) = None

    actor_display_name: (
        str | None
    ) = None


class CoordinatorCaseResponse(APIModel):
    report_reference: str

    observer_id: int

    threat: str
    description: str

    observed_at: (
        datetime | None
    )

    estimated_depth_metres: (
        float | None
    ) = None

    area: (
        str | None
    ) = None

    precise_location: (
        PreciseLocationResponse | None
    ) = None

    status_code: CaseStatus
    status_label: str

    submitted_at: datetime

    owner: CaseOwnerResponse

    evidence: list[
        EvidenceSummary
    ]

    latest_decision: (
        LatestDecisionResponse | None
    ) = None

    triage_context: (
        CaseTriageContext
    )

    ai_assisted: (
        AIAssistedContext | None
    ) = None

    information_exchange: list[
        InformationExchangeEntry
    ] = Field(
        default_factory=list
    )


class InformationRequestCreate(APIModel):
    """
    Coordinator reason for asking the Observer for more
    information.
    """

    reason: str = Field(
        min_length=1,
        max_length=500,
    )

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(
        cls,
        the_value: str,
    ) -> str:
        the_trimmed_reason = (
            the_value.strip()
        )

        if (
            the_trimmed_reason
            == ""
        ):
            raise ValueError(
                "reason must not be empty"
            )

        return (
            the_trimmed_reason
        )


class InformationRequestResponse(APIModel):
    report_reference: str
    status: str
    reason: str
    requested_at: datetime


class ResponseTypeDecisionCreate(APIModel):
    """
    Coordinator US5.4 response decision.
    """

    response_type: str

    notes: (
        str | None
    ) = Field(
        default=None,
        max_length=1000,
    )

    referred_to: (
        str | None
    ) = Field(
        default=None,
        max_length=200,
    )

    @field_validator(
        "response_type"
    )
    @classmethod
    def response_type_must_be_a_database_value(
        cls,
        the_value: str,
    ) -> str:
        the_permitted_response_types = {
            "monitoring_only",
            "refer_or_share",
            "intervention_required",
        }

        if (
            the_value
            not in
            the_permitted_response_types
        ):
            raise ValueError(
                "response_type must be one of: "
                + ", ".join(
                    sorted(
                        the_permitted_response_types
                    )
                )
            )

        return the_value

    @model_validator(
        mode="after"
    )
    def referral_must_name_the_recipient(
        self,
    ):
        if (
            self.response_type
            == "refer_or_share"
        ):
            if (
                self.referred_to
                is None
                or self.referred_to
                .strip()
                == ""
            ):
                raise ValueError(
                    "referred_to is required "
                    "when response_type is "
                    "refer_or_share"
                )

        return self


class ResponseTypeDecisionResponse(
    APIModel
):
    report_reference: str
    response_type: str
    decided_at: datetime
    decided_by: int


class CaseClosureCreate(APIModel):
    """
    What a coordinator supplies to close a case.

    Closure vocabulary is now database-owned through
    closure_reason.is_selectable.

    Python therefore no longer hardcodes the old Iteration
    1 list.
    """

    closure_reason_code: str = Field(
        min_length=1,
        max_length=100,
    )

    public_closure_note: (
        str | None
    ) = Field(
        default=None,
        max_length=1000,
    )

    referred_to: (
        str | None
    ) = Field(
        default=None,
        max_length=200,
    )

    @field_validator(
        "closure_reason_code"
    )
    @classmethod
    def closure_reason_must_not_be_blank(
        cls,
        the_value: str,
    ) -> str:
        the_trimmed_value = (
            the_value.strip()
        )

        if (
            the_trimmed_value
            == ""
        ):
            raise ValueError(
                "closure_reason_code "
                "must not be empty"
            )

        return (
            the_trimmed_value
        )


class CaseClosureResponse(APIModel):
    report_reference: str
    status: str

    closure_reason_code: str

    closed_at: datetime


class EvidenceAssessmentCreate(APIModel):
    """
    Coordinator answers to the two evidence questions.
    """

    evidence_usable: bool

    observation_credible: (
        bool | None
    ) = None

    notes: (
        str | None
    ) = Field(
        default=None,
        max_length=1000,
    )

    related_report_state: (
        str | None
    ) = None

    related_report_reference: (
        str | None
    ) = None

    @model_validator(
        mode="after"
    )
    def credibility_is_required_when_evidence_is_usable(
        self,
    ):
        if (
            self.evidence_usable
            and
            self.observation_credible
            is None
        ):
            raise ValueError(
                "observation_credible is "
                "required when "
                "evidence_usable is true"
            )

        return self


class EvidenceAssessmentResponse(
    APIModel
):
    report_reference: str

    evidence_usable: bool

    observation_credible: (
        bool | None
    ) = None

    status: str

    assessed_at: datetime
    assessed_by: int


# ---------------------------------------------------------------------------
# API-10 Closed-case history schemas.
# ---------------------------------------------------------------------------


class HistoryCodeLabel(APIModel):
    """
    Stable database code plus human-readable label.
    """

    code: str
    label: str


class ReferralHistoryEntry(APIModel):
    referred_to: str
    referred_at: datetime

    note: (
        str | None
    ) = None

    decided_by_name: (
        str | None
    ) = None


class CoordinatorHistoryItem(APIModel):
    """
    One closed case belonging to the authenticated
    coordinator.

    Only public/generalised location is returned.
    """

    report_reference: str

    threat_category: (
        HistoryCodeLabel
    )

    general_location: (
        str | None
    ) = None

    status: HistoryCodeLabel

    submitted_at: datetime

    closed_at: (
        datetime | None
    ) = None

    closure_reason: (
        HistoryCodeLabel | None
    ) = None

    closure_note: (
        str | None
    ) = None

    was_referred: bool

    referrals: list[
        ReferralHistoryEntry
    ] = Field(
        default_factory=list
    )


class CoordinatorHistoryFilters(
    APIModel
):
    closure_reason: (
        str | None
    ) = None

    threat_category: (
        str | None
    ) = None

    closed_from: (
        datetime | None
    ) = None

    closed_to: (
        datetime | None
    ) = None

    was_referred: (
        bool | None
    ) = None


class CoordinatorHistoryResponse(
    APIModel
):
    """
    Filtered, paginated coordinator-owned closed-case
    history.
    """

    items: list[
        CoordinatorHistoryItem
    ]

    page: int
    page_size: int
    total: int

    applied_filters: (
        CoordinatorHistoryFilters
    )