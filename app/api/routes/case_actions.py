# ---------------------------------------------------------------------------
# Coordinator case actions (US5.3, US5.4, US5.5).
#
# Thin HTTP adapters. All policy lives in the services, and domain exceptions
# are not caught here: the global handlers registered in main.py map each
# ServiceError subclass to its own status_code.
#
# The one exception is the closure endpoint, which keeps its DBAPIError
# handling. trg_report_closure_reason is DEFERRABLE INITIALLY DEFERRED, so it
# raises at COMMIT rather than at execute(). The global handlers have no way
# to know a deferred constraint failed or to roll the transaction back.
#
# The path uses reportReference rather than an internal id, because the
# database functions are keyed on report_reference and it is the identifier
# the observer already sees.
# ---------------------------------------------------------------------------
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import DBAPIError

from app.api.dependencies.authorization import CurrentCoordinator
from app.api.dependencies.db import DatabaseSession
from app.schemas.case import (
    CaseClosureCreate,
    CaseClosureResponse,
    EvidenceAssessmentCreate,
    EvidenceAssessmentResponse,
    InformationRequestCreate,
    InformationRequestResponse,
    ResponseTypeDecisionCreate,
    ResponseTypeDecisionResponse,
)
from app.services.case_closure_service import close_case
from app.services.case_decision_service import record_decision
from app.services.case_workflow_service import request_more_information
from app.services.case_assessment_service import record_evidence_assessment


router = APIRouter()


@router.post(
    "/reports/{report_reference}/information-request",
    response_model=InformationRequestResponse,
)
async def create_information_request(
    report_reference: str,
    the_request_input: InformationRequestCreate,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """Ask the observer for more information on an owned case."""

    # the actor comes from the verified token, never from the request
    the_coordinator_id = current_user["user_id"]

    the_result = await request_more_information(
        db=db,
        report_reference=report_reference,
        coordinator_id=the_coordinator_id,
        reason=the_request_input.reason,
    )

    # the status move and its case_event only become permanent here
    await db.commit()

    return InformationRequestResponse(
        report_reference=the_result["report_reference"],
        status=the_result["status"],
        reason=the_result["reason"],
        requested_at=datetime.now(timezone.utc),
    )


@router.post(
    "/reports/{report_reference}/decision",
    response_model=ResponseTypeDecisionResponse,
)
async def create_case_decision(
    report_reference: str,
    the_decision_input: ResponseTypeDecisionCreate,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """Record a response-type decision on an owned case."""

    # the actor comes from the verified token, never from the request
    the_coordinator_id = current_user["user_id"]

    the_result = await record_decision(
        db=db,
        report_reference=report_reference,
        coordinator_id=the_coordinator_id,
        response_type=the_decision_input.response_type,
        notes=the_decision_input.notes,
        referred_to=the_decision_input.referred_to,
    )

    # the decision row only becomes permanent here
    await db.commit()

    return ResponseTypeDecisionResponse(
        report_reference=the_result["report_reference"],
        response_type=the_result["response_type"],
        decided_at=the_result["decided_at"],
        decided_by=the_result["decided_by"],
    )


@router.post(
    "/reports/{report_reference}/close",
    response_model=CaseClosureResponse,
)
async def close_owned_case(
    report_reference: str,
    the_closure_input: CaseClosureCreate,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """Close a case the coordinator owns, recording the reason."""

    # the actor comes from the verified token, never from the request
    the_coordinator_id = current_user["user_id"]

    try:
        the_result = await close_case(
            db=db,
            report_reference=report_reference,
            coordinator_id=the_coordinator_id,
            closure_reason_code=the_closure_input.closure_reason_code,
            public_closure_note=the_closure_input.public_closure_note,
            referred_to=the_closure_input.referred_to,
        )

        # The commit sits INSIDE the try on purpose. trg_report_closure_reason
        # is DEFERRABLE INITIALLY DEFERRED, so a closure that breaks it raises
        # here rather than at execute(). Committing outside the try would
        # return 200 for a close that never happened.
        await db.commit()

    except DBAPIError as the_error:
        # A deferred constraint or a database-side ownership check failed at
        # commit. The detail is deliberately generic: Postgres messages can
        # name internal columns and are not observer-safe.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The case could not be closed in its current state",
        ) from the_error

    return CaseClosureResponse(
        report_reference=the_result["report_reference"],
        status=the_result["status"],
        closure_reason_code=the_result["closure_reason_code"],
        closed_at=datetime.now(timezone.utc),
    )

@router.post(
    "/reports/{report_reference}/evidence-assessment",
    response_model=EvidenceAssessmentResponse,
)
async def assess_case_evidence(
    report_reference: str,
    the_assessment_input: EvidenceAssessmentCreate,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Record the two evidence questions and move the case accordingly.

    The commit sits inside the try because one of the three outcomes closes the
    case, and trg_report_closure_reason is DEFERRABLE INITIALLY DEFERRED, so it
    raises at COMMIT rather than at execute. Committing outside the try would
    return 200 for a closure that never happened.
    """

    # the actor comes from the verified token, never from the request
    the_coordinator_id = current_user["user_id"]

    try:
        the_result = await record_evidence_assessment(
            db=db,
            report_reference=report_reference,
            coordinator_id=the_coordinator_id,
            evidence_usable=the_assessment_input.evidence_usable,
            observation_credible=the_assessment_input.observation_credible,
            notes=the_assessment_input.notes,
        )

        await db.commit()

    except DBAPIError as the_error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The evidence assessment could not be recorded in this case's current state",
        ) from the_error

    return EvidenceAssessmentResponse(
        report_reference=the_result["report_reference"],
        evidence_usable=the_result["evidence_usable"],
        observation_credible=the_result["observation_credible"],
        status=the_result["status"],
        assessed_at=the_result["assessed_at"],
        assessed_by=the_result["assessed_by"],
    )