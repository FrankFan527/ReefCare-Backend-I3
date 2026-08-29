# ---------------------------------------------------------------------------
# Case workflow policy (US5.3, US5.4, US5.5).
#
# Services decide whether an action is allowed; repositories carry it out.
#
# SECURITY NOTE FOR REVIEWERS: reefcare_change_status() does not check that the
# actor owns the case. It takes p_actor_user_id but only records it in the
# audit event. So the ownership check below is not a convenience for producing
# a nicer error, it is the only thing preventing one coordinator from moving
# another coordinator's case. Compare reefcare_close_report(), which does check
# ownership in the database.
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError, WorkflowError
from app.repositories.case_repository import (
    change_status,
    get_report_owner,
    transition_is_permitted,
)


# the status a case moves to when a coordinator asks for more information
NEEDS_MORE_INFO_STATUS: str = "needs_more_info"

# case_event.event_type already permits this value, which is why Iteration 1
# needs no separate information_request table
INFORMATION_REQUEST_EVENT: str = "info_requested"


async def load_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> dict:
    """
    Fetch a case and confirm this coordinator owns it.

    Uses get_report_owner(...), which returns claimed_by_user_id and
    status_code for the report.

    Raises NotFoundError when the reference does not exist or the report was
    withdrawn, and AuthorizationError when it belongs to somebody else.

    An unclaimed case also raises AuthorizationError rather than a separate
    error, because from the caller's point of view the answer is the same:
    they are not the owner and may not act on it.
    """

    the_case = await get_report_owner(
        db=db,
        report_reference=report_reference,
    )

    if the_case is None:
        raise NotFoundError(f"Report {report_reference} not found")

    if the_case["claimed_by_user_id"] != coordinator_id:
        raise AuthorizationError(
            f"Report {report_reference} is not owned by you"
        )

    return dict(the_case)


async def validate_status_transition(
    db: AsyncSession,
    from_status_code: str,
    to_status_code: str,
) -> None:
    """
    Check the move against case_status_transition before attempting it.

    An early-feedback check only. PostgreSQL remains authoritative and will
    reject an unlisted transition regardless of what this concludes.
    """

    the_move_is_allowed = await transition_is_permitted(
        db=db,
        from_status_code=from_status_code,
        to_status_code=to_status_code,
    )

    if not the_move_is_allowed:
        raise WorkflowError(
            f"A case cannot move from {from_status_code} to {to_status_code}"
        )


async def request_more_information(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    reason: str,
) -> dict:
    """
    Ask the observer for more information on a case this coordinator owns.

    Order matters. Ownership is checked before anything else, so a coordinator
    who does not own the case learns nothing about its current state.

    The reason is passed as the note, which reefcare_change_status() writes
    into case_event in the same transaction as the status move. That is what
    makes it visible in the observer's timeline without a separate table.

    event_type is passed explicitly so the move records as info_requested
    rather than the default status_change.

    The caller commits.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    await validate_status_transition(
        db=db,
        from_status_code=the_case["status_code"],
        to_status_code=NEEDS_MORE_INFO_STATUS,
    )

    the_new_status_code = await change_status(
        db=db,
        report_reference=report_reference,
        status_code=NEEDS_MORE_INFO_STATUS,
        actor_user_id=coordinator_id,
        note=reason,
        event_type=INFORMATION_REQUEST_EVENT,
    )

    return {
        "report_reference": report_reference,
        "status": the_new_status_code,
        "reason": reason,
    }