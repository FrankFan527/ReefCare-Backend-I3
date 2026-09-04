from datetime import datetime

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from app.core.enums import CaseStatus
from app.schemas.common import APIModel


class CaseOwnerResponse(APIModel):
    id: int
    display_name: str


class CoordinatorQueueItem(APIModel):
    report_reference: str

    threat: str
    area: str | None = None

    status_label: str

    submitted_at: datetime
    hours_in_queue: int


class CoordinatorQueueResponse(APIModel):
    items: list[CoordinatorQueueItem]

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
    latitude: float | None = None
    longitude: float | None = None

    uncertainty_metres: int | None = None
    confidence_label: str | None = None
    source_label: str | None = None

    relocation_notes: str | None = None


class EvidenceSummary(APIModel):
    evidence_id: int
    media_type: str

    captured_at: datetime | None = None
    uploaded_at: datetime


class CoordinatorCaseResponse(APIModel):
    report_reference: str

    observer_id: int

    threat: str
    description: str

    estimated_depth_metres: float | None = None

    area: str | None = None

    precise_location: PreciseLocationResponse | None = None

    status_code: CaseStatus
    status_label: str

    submitted_at: datetime

    owner: CaseOwnerResponse

    evidence: list[EvidenceSummary]


class InformationRequestCreate(APIModel):
    """
    The coordinator's reason for asking the observer for more information.

    Iteration 1 has no separate information_request table.
    The reason is written into case_event.note by
    reefcare_change_status().
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

        if the_trimmed_reason == "":
            raise ValueError(
                "reason must not be empty"
            )

        return the_trimmed_reason


class InformationRequestResponse(APIModel):
    """
    Confirmation that the case moved to needs_more_info.
    """

    report_reference: str
    status: str
    reason: str
    requested_at: datetime


class ResponseTypeDecisionCreate(APIModel):
    """
    A coordinator's Iteration 1 response-type decision
    on an owned case.
    """

    response_type: str

    notes: str | None = Field(
        default=None,
        max_length=1000,
    )

    referred_to: str | None = Field(
        default=None,
        max_length=200,
    )

    @field_validator("response_type")
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
            not in the_permitted_response_types
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

    @model_validator(mode="after")
    def referral_must_name_the_recipient(
        self,
    ):
        if (
            self.response_type
            == "refer_or_share"
        ):
            if (
                self.referred_to is None
                or self.referred_to.strip()
                == ""
            ):
                raise ValueError(
                    "referred_to is required "
                    "when response_type is "
                    "refer_or_share"
                )

        return self


class ResponseTypeDecisionResponse(APIModel):
    """
    Confirmation that a decision was recorded.
    """

    report_reference: str
    response_type: str
    decided_at: datetime
    decided_by: int


class CaseClosureCreate(APIModel):
    """
    What a coordinator supplies to close a case.
    """

    closure_reason_code: str

    public_closure_note: str | None = Field(
        default=None,
        max_length=1000,
    )

    referred_to: str | None = Field(
        default=None,
        max_length=200,
    )

    @field_validator(
        "closure_reason_code"
    )
    @classmethod
    def closure_reason_must_be_iteration_one(
        cls,
        the_value: str,
    ) -> str:
        the_iteration_one_reasons = {
            "referred_other_org",
            "monitored_no_action",
            "not_substantiated",
            "no_responsible_partner",
            "logged_for_reference",
        }

        if (
            the_value
            not in the_iteration_one_reasons
        ):
            raise ValueError(
                "closure_reason_code must "
                "be one of: "
                + ", ".join(
                    sorted(
                        the_iteration_one_reasons
                    )
                )
            )

        return the_value


class CaseClosureResponse(APIModel):
    """
    Confirmation that a case was closed.
    """

    report_reference: str
    status: str
    closure_reason_code: str
    closed_at: datetime