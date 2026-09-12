# ---------------------------------------------------------------------------
# Coordinator case actions (US5.3, US5.4, US5.5, US7.1).
#
# Thin HTTP adapters. All policy lives in the services, and domain exceptions
# are not caught here: the global handlers registered in main.py map each
# ServiceError subclass to its own status_code.
#
# The exceptions are the closure, evidence-assessment and action endpoints,
# which keep their DBAPIError handling. trg_report_closure_reason is
# DEFERRABLE INITIALLY DEFERRED, so it raises at COMMIT rather than at
# execute(). The global handlers have no way to know a deferred constraint
# failed or to roll the transaction back.
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
from app.schemas.action import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionTypeOption,
)
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
from app.services.case_action_service import (
    list_action_type_options,
    list_actions_for_owned_case,
    record_action,
)
from app.services.case_assessment_service import record_evidence_assessment
from app.services.case_closure_service import close_case
from app.services.case_decision_service import record_decision
from app.services.case_workflow_service import request_more_information


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


# ---------------------------------------------------------------------------
# US7.1 Basic conservation action record.
#
# Deliberately small. Section 10.5 of the Iteration 2 backend document is
# explicit that E7 must not grow into the deferred Iteration 3 monitoring
# workflow, so there is no update endpoint and no delete endpoint: an action is
# superseded by recording a later one.
# ---------------------------------------------------------------------------


@router.get(
    "/action-types",
    response_model=list[ActionTypeOption],
)
async def get_action_types(
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Return the action vocabulary a coordinator may currently choose from.

    Read from the action_type reference table rather than a Python constant, so
    labels can be corrected without a redeploy.
    """

    the_options = await list_action_type_options(db=db)

    return [
        ActionTypeOption(
            code=the_option["code"],
            label=the_option["label"],
            description=the_option["description"],
        )
        for the_option in the_options
    ]


@router.post(
    "/reports/{report_reference}/actions",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_case_action(
    report_reference: str,
    the_action_input: ActionCreate,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Record a planned or completed conservation action on an owned case.

    The commit sits inside the try for the same reason as closure and evidence
    assessment: the action may move the case status, and a transition the
    database refuses must not return 201 for a row that was rolled back.
    """

    # the actor comes from the verified token, never from the request
    the_coordinator_id = current_user["user_id"]

    try:
        the_result = await record_action(
            db=db,
            report_reference=report_reference,
            coordinator_id=the_coordinator_id,
            action_type_code=the_action_input.action_type_code,
            action_state=the_action_input.action_state.value,
            action_date=the_action_input.action_date,
            responsible_team=the_action_input.responsible_team,
            notes=the_action_input.notes,
        )

        await db.commit()

    except DBAPIError as the_error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The action could not be recorded in this case's current state",
        ) from the_error

    return ActionResponse(**the_result)


@router.get(
    "/reports/{report_reference}/actions",
    response_model=ActionListResponse,
)
async def get_case_actions(
    report_reference: str,
    current_user: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Return every action recorded against an owned case, oldest first.

    Ownership is verified in the service before any detail is returned: an
    action names a responsible team and describes intended or completed
    conservation work, which is not queue-safe information.
    """

    the_coordinator_id = current_user["user_id"]

    the_actions = await list_actions_for_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=the_coordinator_id,
    )

    return ActionListResponse(
        report_reference=report_reference,
        items=[
            ActionResponse(**the_action)
            for the_action in the_actions
        ],
        total=len(the_actions),
    )