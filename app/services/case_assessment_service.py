# ---------------------------------------------------------------------------
# Evidence assessment workflow (US5.3).
#
# The two questions from the proposal decision tree:
#   Q1  Is the evidence usable?      -> case_decision.evidence_usable
#   Q2  Is the observation credible? -> case_decision.observation_credible
#
# The three outcomes are not chosen by the client. They are derived from the
# answers, because which status is legal depends on where the case currently
# is, and the client has no way to know that. The destinations come straight
# from case_status_transition, which already carries them with the reasoning
# in its note column:
#
#   under_review -> needs_more_info            Q1: evidence not usable
#   under_review -> evidence_accepted          Q2: observation credible
#   under_review -> closed_not_substantiated   Q2: evidence does not support it
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseOperationError, WorkflowError
from app.repositories.case_decision_repository import save_evidence_assessment
from app.repositories.case_repository import change_status
from app.services.case_closure_service import close_case
from app.services.case_workflow_service import (
    load_owned_case,
    request_more_information,
    validate_status_transition,
)


# An assessment answers questions about a case somebody has actually opened.
# under_review is the only state where both questions are meaningful, and it is
# the state Frank's start-review endpoint leaves a claimed case in.
STATUS_THAT_MAY_BE_ASSESSED: str = "under_review"

EVIDENCE_ACCEPTED_STATUS: str = "evidence_accepted"

# the closure reason used when the evidence does not support the report
NOT_SUBSTANTIATED_REASON: str = "not_substantiated"

# the note recorded against the case_event when evidence cannot be used
INSUFFICIENT_EVIDENCE_REASON: str = (
    "The evidence provided could not be used to assess this report. "
    "Please add a clearer photograph or more detail."
)


def validate_case_is_ready_for_assessment(current_status_code: str) -> None:
    """
    Only a case that is under review may be assessed.

    A case still in claimed has not been opened yet, and a case already past
    evidence_accepted has been assessed once. Repeating it would write a second
    assessment row that disagrees with the first.
    """

    if current_status_code != STATUS_THAT_MAY_BE_ASSESSED:
        raise WorkflowError(
            f"Evidence can only be assessed while the case is "
            f"{STATUS_THAT_MAY_BE_ASSESSED}; this case is {current_status_code}"
        )


async def record_evidence_assessment(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    evidence_usable: bool,
    observation_credible: bool | None = None,
    notes: str | None = None,
) -> dict:
    """
    Record the assessment and move the case to wherever the answers lead.

    Ownership is checked before the status, so a coordinator probing somebody
    else's case learns nothing about its state from the error message.

    IMPORTANT: the not-substantiated outcome goes through close_case rather
    than change_status. closed_not_substantiated is a terminal status, so
    trg_report_closure_reason demands a closure reason at COMMIT. A plain
    status change would be rejected there rather than at execute time.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    validate_case_is_ready_for_assessment(
        current_status_code=the_case["status_code"],
    )

    # ---- Q1 no: the evidence cannot be used, so ask the observer for more ----
    #
    # This reuses the existing information-request path rather than repeating
    # it, so the reason still lands in case_event.note with the info_requested
    # event type and the observer timeline reads correctly.
    if not evidence_usable:
        the_assessment = await save_evidence_assessment(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            evidence_usable=False,
            observation_credible=None,
            decision_note=notes,
        )

        if the_assessment is None:
            raise DatabaseOperationError(
                "The evidence assessment could not be recorded"
            )

        the_result = await request_more_information(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            reason=notes if notes else INSUFFICIENT_EVIDENCE_REASON,
        )

        return {
            "report_reference": report_reference,
            "evidence_usable": False,
            "observation_credible": None,
            "status": the_result["status"],
            "assessed_at": the_assessment["decided_at"],
            "assessed_by": the_assessment["coordinator_id"],
        }

    # ---- Q1 yes: record the assessment, then Q2 decides where it goes ----
    the_assessment = await save_evidence_assessment(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
        evidence_usable=True,
        observation_credible=observation_credible,
        decision_note=notes,
    )

    if the_assessment is None:
        raise DatabaseOperationError(
            "The evidence assessment could not be recorded"
        )

    # ---- Q2 no: the evidence does not support the report, so close it ----
    if not observation_credible:
        the_closure = await close_case(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            closure_reason_code=NOT_SUBSTANTIATED_REASON,
            public_closure_note=notes,
        )

        return {
            "report_reference": report_reference,
            "evidence_usable": True,
            "observation_credible": False,
            "status": the_closure["status"],
            "assessed_at": the_assessment["decided_at"],
            "assessed_by": the_assessment["coordinator_id"],
        }

    # ---- Q2 yes: the report stands, move it to evidence_accepted ----
    await validate_status_transition(
        db=db,
        from_status_code=the_case["status_code"],
        to_status_code=EVIDENCE_ACCEPTED_STATUS,
    )

    the_new_status_code = await change_status(
        db=db,
        report_reference=report_reference,
        status_code=EVIDENCE_ACCEPTED_STATUS,
        actor_user_id=coordinator_id,
        note=notes,
        event_type="decision_recorded",
    )

    return {
        "report_reference": report_reference,
        "evidence_usable": True,
        "observation_credible": True,
        "status": the_new_status_code,
        "assessed_at": the_assessment["decided_at"],
        "assessed_by": the_assessment["coordinator_id"],
    }