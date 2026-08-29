# ---------------------------------------------------------------------------
# Case closure policy (US5.5).
#
# Unlike the other two 5.5 endpoints, reefcare_close_report() checks ownership
# itself. The check here still runs first so the caller gets a clean 403
# rather than a raw Postgres exception, but it is no longer the only defence.
#
# Closure is the one irreversible action in the system: case_status_transition
# has no move out of a terminal status. Everything below is written on the
# assumption that a wrong close cannot be undone through the API.
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, WorkflowError
from app.repositories.case_decision_repository import get_latest_decision
from app.repositories.case_repository import (
    close_report,
    get_closure_reason,
    transition_is_permitted,
)
from app.services.case_workflow_service import load_owned_case


# Which terminal status each closure reason lands in.
#
# This is not free choice. reefcare_close_report() takes the reason and the
# terminal status separately, then routes the move through
# reefcare_change_status(), which enforces case_status_transition. Pairing them
# here means the client sends only the reason and cannot request a status that
# contradicts it.
TERMINAL_STATUS_FOR_CLOSURE_REASON: dict[str, str] = {
    "referred_other_org": "closed_no_action",
    "monitored_no_action": "closed_no_action",
    "not_substantiated": "closed_not_substantiated",
    "no_responsible_partner": "closed_no_partner",
    "logged_for_reference": "closed_logged",
}

# Which closure reason a recorded decision implies.
#
# Mirrors the CASE expression inside reefcare_close_report(), which derives
# response_type from the closure reason. Without this check a coordinator
# could record "refer_or_share" and then close as "not_substantiated",
# leaving two case_decision rows that contradict each other.
CLOSURE_REASON_FOR_RESPONSE_TYPE: dict[str, str] = {
    "refer_or_share": "referred_other_org",
    "monitoring_only": "monitored_no_action",
    "no_responsible_partner": "no_responsible_partner",
}


async def validate_closure_rules(
    db: AsyncSession,
    closure_reason_code: str,
    public_closure_note: str | None,
) -> dict:
    """
    Check the closure reason exists, is selectable, and has its required note.

    requires_note comes from the reference data rather than a hardcoded list,
    so a reason added later carries its own rule.
    """

    the_reason = await get_closure_reason(
        db=db,
        closure_reason_code=closure_reason_code,
    )

    if the_reason is None:
        raise NotFoundError(f"Unknown closure reason: {closure_reason_code}")

    if the_reason["iteration_added"] > 1:
        raise WorkflowError(
            f"Closure reason {closure_reason_code} is not selectable in Iteration 1"
        )

    if the_reason["requires_note"]:
        if public_closure_note is None or public_closure_note.strip() == "":
            raise WorkflowError(
                f"Closure reason {closure_reason_code} requires a closure note"
            )

    return the_reason


def validate_decision_closure_combination(
    response_type: str | None,
    closure_reason_code: str,
) -> None:
    """
    Prevent a closure reason that contradicts the recorded decision.

    Only the three response types that map to a specific reason are checked.
    intervention_required has no natural closure reason, so any Iteration 1
    reason is allowed after it.
    """

    if response_type is None:
        return

    the_expected_reason = CLOSURE_REASON_FOR_RESPONSE_TYPE.get(response_type)

    if the_expected_reason is None:
        return

    if the_expected_reason != closure_reason_code:
        raise WorkflowError(
            f"A case decided as {response_type} cannot be closed as "
            f"{closure_reason_code}; expected {the_expected_reason}"
        )


async def close_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    closure_reason_code: str,
    public_closure_note: str | None = None,
    referred_to: str | None = None,
) -> dict:
    """
    Close a case the coordinator owns.

    Order: ownership, then closure reason validity, then that a decision
    exists, then that the decision and reason agree, then that the resulting
    terminal status is actually reachable from where the case is now.

    US5.5 requires a decision before closure and nothing in the database
    enforces that ordering, so it is checked here.

    The caller commits, and must do so inside its own error handling: the
    closure trigger is deferred and raises at COMMIT.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    await validate_closure_rules(
        db=db,
        closure_reason_code=closure_reason_code,
        public_closure_note=public_closure_note,
    )

    the_existing_decision = await get_latest_decision(
        db=db,
        report_reference=report_reference,
    )

    if the_existing_decision is None:
        raise WorkflowError(
            "A case must have a recorded decision before it can be closed"
        )

    validate_decision_closure_combination(
        response_type=the_existing_decision["response_type"],
        closure_reason_code=closure_reason_code,
    )

    the_terminal_status_code = TERMINAL_STATUS_FOR_CLOSURE_REASON[closure_reason_code]

    # the terminal status must be reachable from where the case is now
    the_move_is_allowed = await transition_is_permitted(
        db=db,
        from_status_code=the_case["status_code"],
        to_status_code=the_terminal_status_code,
    )

    if not the_move_is_allowed:
        raise WorkflowError(
            f"A case in {the_case['status_code']} cannot be closed as "
            f"{closure_reason_code}, which would move it to "
            f"{the_terminal_status_code}"
        )

    the_final_status_code = await close_report(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
        closure_reason_code=closure_reason_code,
        terminal_status_code=the_terminal_status_code,
        note=public_closure_note,
        referred_to=referred_to,
    )

    return {
        "report_reference": report_reference,
        "status": the_final_status_code,
        "closure_reason_code": closure_reason_code,
    }