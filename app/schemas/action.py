# ---------------------------------------------------------------------------
# Conservation action record contracts (US7.1).
#
# Deliberately small. Section 10.5 of the Iteration 2 backend document is
# explicit that E7 must not expand into the deferred Iteration 3 monitoring
# workflow, so these models carry a single action statement and nothing that
# would begin to look like a work-tracking system.
#
# action_type_code rather than an integer id: the vocabulary lives in the
# action_type reference table and the frontend already reads reference data by
# code elsewhere, so the API stays readable and the database stays the source
# of truth.
# ---------------------------------------------------------------------------
from datetime import date, datetime

from pydantic import Field, model_validator

from app.core.enums import ActionState, CaseStatus
from app.schemas.common import APIModel


class ActionCreate(APIModel):
    """
    One action statement submitted by the owning coordinator.

    action_date is a calendar date, not a timestamp. A coordinator recording a
    clean-up knows the day it happened, not the instant, and asking for a
    timestamp would invent precision nobody supplied.
    """

    action_type_code: str = Field(min_length=1, max_length=50)
    action_state: ActionState

    action_date: date | None = None
    responsible_team: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def action_taken_requires_a_date(self):
        """
        US7.1 AC4 made visible at the API boundary.

        case_action_taken_needs_date enforces the same rule in PostgreSQL and
        remains the real guarantee. Checking it here as well turns what would
        otherwise be an opaque 500 from a failed CHECK into a 422 that names
        the field.
        """

        if (
            self.action_state == ActionState.ACTION_TAKEN
            and self.action_date is None
        ):
            raise ValueError(
                "actionDate is required when actionState is action_taken"
            )

        return self


class ActionResponse(APIModel):
    """
    One recorded action, plus the case status that resulted from it.

    status_code is included because the coordinator needs to see whether the
    action moved the case. Recording a second planned action of a different
    type leaves the case where it already was, and the response should say so
    rather than leaving the frontend to guess.
    """

    case_action_id: int
    report_reference: str

    action_type_code: str
    action_type_label: str

    action_state: ActionState
    action_date: date | None = None

    responsible_team: str | None = None
    notes: str | None = None

    status_code: CaseStatus

    created_by: int
    created_by_name: str | None = None
    created_at: datetime


class ActionListResponse(APIModel):
    report_reference: str

    items: list[ActionResponse]
    total: int


class ActionTypeOption(APIModel):
    """
    One selectable entry from the action_type reference table.
    """

    code: str
    label: str
    description: str | None = None