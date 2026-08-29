# ---------------------------------------------------------------------------
# Case decision policy (US5.4).
#
# SECURITY NOTE: recording a decision is a plain INSERT with no sanctioned
# database function behind it, so there is no ownership check in Postgres.
# As with request_more_information, load_owned_case below is the only thing
# preventing a coordinator from recording a decision on somebody else's case.
#
# This endpoint deliberately does not move the case status. The doc scopes
# save_case_decision to non-terminal fields, terminal moves belong to
# reefcare_close_report(), and mapping a response type onto a status
# transition is a decision the team has not made. intervention_required in
# particular has no corresponding status in case_status_transition.
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import WorkflowError
from app.repositories.case_decision_repository import save_case_decision
from app.services.case_workflow_service import load_owned_case


# a decision only makes sense once the coordinator has actually reviewed the case
STATUSES_THAT_MAY_RECEIVE_A_DECISION: set[str] = {
    "under_review",
    "evidence_accepted",
    "monitoring",
    "referred",
}
# the three selectable via the decision endpoint, per the US5.4 team decision.
# case_decision_response_type_valid also permits no_responsible_partner, but
# that stays on the closure path: reefcare_close_report() derives it from the
# no_responsible_partner closure reason
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
    Check the response type and its required companion field.

    Duplicates the checks already in ResponseTypeDecisionCreate on purpose.
    The schema protects the HTTP route; this protects the service if it is
    ever called from somewhere else, such as a test or a future endpoint.
    """

    if response_type not in PERMITTED_RESPONSE_TYPES:
        raise WorkflowError(
            "response_type must be one of: "
            + ", ".join(sorted(PERMITTED_RESPONSE_TYPES))
        )

    if response_type == "refer_or_share":
        if referred_to is None or referred_to.strip() == "":
            raise WorkflowError(
                "referred_to is required when response_type is refer_or_share"
            )


def validate_case_is_ready_for_a_decision(current_status_code: str) -> None:
    """
    A decision only belongs on a case that has been reviewed.

    Recording one on a case still sitting in received or claimed would mean a
    coordinator decided the outcome before opening it. Closed cases are
    excluded for the obvious reason.
    """

    if current_status_code not in STATUSES_THAT_MAY_RECEIVE_A_DECISION:
        raise WorkflowError(
            f"A decision cannot be recorded while the case is {current_status_code}"
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
    Record a coordinator's response-type decision on a case they own.

    Ownership is checked first, so a coordinator who does not own the case
    learns nothing about its state from the error.

    The caller commits.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    validate_case_is_ready_for_a_decision(
        current_status_code=the_case["status_code"],
    )

    validate_response_type(
        response_type=response_type,
        referred_to=referred_to,
    )

    the_saved_decision = await save_case_decision(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
        response_type=response_type,
        decision_note=notes,
        referred_to=referred_to,
    )

    return {
        "report_reference": report_reference,
        "response_type": the_saved_decision["response_type"],
        "decided_at": the_saved_decision["decided_at"],
        "decided_by": the_saved_decision["coordinator_id"],
    }