# ---------------------------------------------------------------------------
# Case decision policy (US5.4).
#
# SECURITY NOTE:
# Recording a response decision is a plain INSERT with no sanctioned
# database function behind it, so PostgreSQL does not independently verify
# case ownership for this operation.
#
# load_owned_case(...) is therefore required before any decision is saved.
#
# US5.4 starts only AFTER US5.3 has accepted the evidence. A normal response
# decision must therefore be recorded while the case is in
# evidence_accepted.
#
# The decision endpoint deliberately does not move the case status.
# response_type is persisted as the coordinator's recommendation/decision.
# Terminal status changes remain the responsibility of US5.5 closure through
# reefcare_close_report(...).
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import WorkflowError
from app.repositories.case_decision_repository import (
    save_case_decision,
)
from app.services.case_workflow_service import (
    load_owned_case,
)


# US5.4 begins only after US5.3 has accepted the evidence.
DECISION_READY_STATUS: str = (
    CaseStatus.EVIDENCE_ACCEPTED.value
)


# The three response types defined by US5.4.
#
# no_responsible_partner is deliberately NOT selectable here.
# That value belongs to the US5.5 closure path.
PERMITTED_RESPONSE_TYPES: set[str] = {
    "monitoring_only",
    "refer_or_share",
    "intervention_required",
}


def validate_response_type(
    response_type: str,
    referred_to: str | None,
) -> None:
    """
    Validate the coordinator's selected US5.4 response type.

    The same values are also validated by
    ResponseTypeDecisionCreate at the HTTP boundary.

    Keeping the validation here protects the service if it
    is later called from another endpoint, test, or internal
    workflow.
    """

    if response_type not in PERMITTED_RESPONSE_TYPES:
        raise WorkflowError(
            "response_type must be one of: "
            + ", ".join(
                sorted(PERMITTED_RESPONSE_TYPES)
            )
        )

    if response_type == "refer_or_share":
        if (
            referred_to is None
            or referred_to.strip() == ""
        ):
            raise WorkflowError(
                "referred_to is required when "
                "response_type is refer_or_share"
            )


def validate_case_is_ready_for_a_decision(
    current_status_code: str,
) -> None:
    """
    Enforce the US5.3 -> US5.4 workflow boundary.

    US5.4 explicitly begins after the evidence has been
    accepted.

    Therefore:
        under_review      -> not ready
        needs_more_info   -> not ready
        evidence_accepted -> ready

    This prevents a coordinator from bypassing the evidence
    usability/credibility assessment and recording a
    response decision directly from under_review.
    """

    if current_status_code != DECISION_READY_STATUS:
        raise WorkflowError(
            "A response decision can only be recorded "
            "after the evidence has been accepted"
        )


async def record_decision(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    response_type: str,
    notes: str | None = None,
    referred_to: str | None = None,
) -> dict:
    """
    Record a US5.4 response-type decision on an owned case.

    Workflow:
        ownership check
        -> evidence_accepted state check
        -> response-type validation
        -> decision persistence

    Ownership is checked first so a coordinator who does
    not own the case cannot use validation errors to learn
    its current workflow state.

    The caller owns the transaction commit.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    validate_case_is_ready_for_a_decision(
        current_status_code=the_case[
            "status_code"
        ],
    )

    validate_response_type(
        response_type=response_type,
        referred_to=referred_to,
    )

    the_saved_decision = (
        await save_case_decision(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            response_type=response_type,
            decision_note=notes,
            referred_to=referred_to,
        )
    )

    return {
        "report_reference": report_reference,
        "response_type": (
            the_saved_decision[
                "response_type"
            ]
        ),
        "decided_at": (
            the_saved_decision[
                "decided_at"
            ]
        ),
        "decided_by": (
            the_saved_decision[
                "coordinator_id"
            ]
        ),
    }