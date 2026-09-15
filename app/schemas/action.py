from datetime import (
    date,
    datetime,
)

from pydantic import (
    Field,
    model_validator,
)

from app.core.enums import (
    ActionState,
    CaseStatus,
)
from app.schemas.common import (
    APIModel,
)


class ActionTypeOption(APIModel):
    code: str
    label: str
    description: str | None = None


class ActionEvidenceSummary(APIModel):
    """
    Safe metadata for evidence attached to one
    conservation action.

    file_reference is deliberately absent.
    """

    evidence_id: int
    media_type: str

    file_size_bytes: (
        int | None
    ) = None

    uploaded_at: datetime


class ActionEvidenceResponse(
    ActionEvidenceSummary
):
    """
    Confirmation that one private evidence file was
    attached to an action.
    """

    case_action_id: int


class ActionCreate(APIModel):
    action_type_code: str = Field(
        min_length=1,
        max_length=100,
    )

    action_state: ActionState

    action_date: (
        date | None
    ) = None

    responsible_team: (
        str | None
    ) = Field(
        default=None,
        max_length=200,
    )

    notes: (
        str | None
    ) = Field(
        default=None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def action_taken_requires_date(
        self,
    ):
        if (
            self.action_state
            == ActionState.ACTION_TAKEN
            and self.action_date
            is None
        ):
            raise ValueError(
                "actionDate is required when "
                "actionState is action_taken"
            )

        return self


class ActionResponse(APIModel):
    case_action_id: int
    case_event_id: int

    report_reference: str

    action_type_code: str
    action_type_label: str

    action_state: ActionState

    action_date: (
        date | None
    ) = None

    responsible_team: (
        str | None
    ) = None

    notes: (
        str | None
    ) = None

    status_code: CaseStatus

    created_by: int

    created_by_name: (
        str | None
    ) = None

    created_at: datetime

    evidence: list[
        ActionEvidenceSummary
    ] = Field(
        default_factory=list
    )


class ActionListResponse(APIModel):
    report_reference: str

    items: list[
        ActionResponse
    ]

    total: int