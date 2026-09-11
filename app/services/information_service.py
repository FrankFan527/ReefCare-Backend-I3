# ---------------------------------------------------------------------------
# Observer information response policy (US5.3 AC3, US6.3).
#
# Services decide whether an action is allowed; repositories carry it out.
#
# SECURITY NOTE: this is the mirror image of case_workflow_service. There,
# load_owned_case() is the only thing stopping a coordinator acting on another
# coordinator's case. Here, get_report_for_observer() is the only thing
# stopping an observer answering somebody else's information request.
# reefcare_change_status() records p_actor_user_id in the audit event but does
# not check who the actor is, so nothing below the service layer will catch it.
#
# US6.3 AC3 is satisfied by what this module does NOT do. The claim is never
# cleared and no new report is created: the response moves the case status and
# writes an event, and report.claimed_by_user_id is left exactly as it was. The
# same coordinator who asked the question gets the answer.
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, WorkflowError
from app.repositories.case_repository import change_status
from app.repositories.information_repository import (
    INFORMATION_RESPONSE_EVENT,
    NEEDS_MORE_INFO_STATUS,
    get_open_information_request,
    get_report_for_observer,
    list_information_exchange,
)


# Where a case returns to once the observer has answered. The transition
# needs_more_info -> under_review is already permitted, seeded in Iteration 1
# with the note "Observer responded", which is precisely this action.
STATUS_AFTER_RESPONSE: str = "under_review"


async def load_observer_report(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> dict:
    """
    Fetch a report and confirm this observer submitted it.

    A report belonging to another observer raises NotFoundError rather than an
    authorisation error. The distinction matters: telling somebody that a
    report exists but is not theirs confirms the reference is real, which lets
    an attacker enumerate valid report references by trying them.
    """

    the_report = await get_report_for_observer(
        db=db,
        report_reference=report_reference,
        observer_id=observer_id,
    )

    if the_report is None:
        raise NotFoundError(f"Report {report_reference} not found")

    return the_report


async def get_open_request_for_observer(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> dict | None:
    """
    Return the information request awaiting this observer's answer, if any.

    US5.3 AC2 and US6.3 AC1: the observer must see what was asked, not just
    that something was asked.
    """

    await load_observer_report(
        db=db,
        report_reference=report_reference,
        observer_id=observer_id,
    )

    return await get_open_information_request(
        db=db,
        report_reference=report_reference,
    )


async def respond_to_information_request(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
    response_text: str,
) -> dict:
    """
    Attach an observer's answer to an existing case and return it for review.

    Order matters. Ownership is checked first, then whether a request is
    actually open, so an observer probing a report they do not own learns
    nothing about its state.

    The status check is deliberately against needs_more_info rather than
    against the transition table alone. A case in under_review has a permitted
    path to needs_more_info, but that is the coordinator's move to make, not
    the observer's; without this check an observer could answer a question
    nobody had asked.

    The response text is passed as the note, which reefcare_change_status()
    writes into case_event in the same transaction as the status move. That is
    what makes it visible to the coordinator, and it is what satisfies US6.3
    AC5: the event carries both occurred_at and actor_user_id.

    The caller commits.
    """

    the_report = await load_observer_report(
        db=db,
        report_reference=report_reference,
        observer_id=observer_id,
    )

    if the_report["status_code"] != NEEDS_MORE_INFO_STATUS:
        raise WorkflowError(
            "There is no open information request on this report"
        )

    the_open_request = await get_open_information_request(
        db=db,
        report_reference=report_reference,
    )

    if the_open_request is None:
        # The case is in needs_more_info but no request event exists. That
        # should be impossible through the API, and it means the case history
        # has been edited outside the application.
        raise WorkflowError(
            "This report is awaiting information but no request was recorded"
        )

    the_new_status_code = await change_status(
        db=db,
        report_reference=report_reference,
        status_code=STATUS_AFTER_RESPONSE,
        actor_user_id=observer_id,
        note=response_text,
        event_type=INFORMATION_RESPONSE_EVENT,
    )

    return {
        "report_reference": report_reference,
        "status": the_new_status_code,
        "response_text": response_text,
        # US6.3 AC3 proved in the response rather than asserted: the same
        # coordinator who asked is still the owner.
        "coordinator_retained": the_report["claimed_by_user_id"],
    }


async def get_information_exchange(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return the full request and response history for one case.

    No ownership check here on purpose. This is called from the coordinator
    case endpoint, which has already established ownership through
    load_owned_case(), and repeating the check with a coordinator id would
    require this function to know which kind of user is asking.
    """

    return await list_information_exchange(
        db=db,
        report_reference=report_reference,
    )