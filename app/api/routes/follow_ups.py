# ---------------------------------------------------------------------------
# US7.1 Conservation follow-up and US7.2 follow-up monitoring — routes.
#
# Mounted under /coordinator. Routes stay thin: the coordinator role comes
# from CurrentCoordinator, everything else is in follow_up_service.py.
#
# The Iteration 2 /actions routes are untouched and keep working. These add
# the wider follow-up record on the same history.
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Query, status

from app.api.dependencies.authorization import CurrentCoordinator
from app.api.dependencies.db import DatabaseSession
from app.schemas.follow_up import (
    FollowUpCorrection,
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    MonitoringConditionOption,
    MonitoringCreate,
)
from app.services import follow_up_service


router = APIRouter()


@router.get(
    "/monitoring-conditions",
    response_model=list[MonitoringConditionOption],
)
async def get_monitoring_conditions(
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US7.2 AC4. The controlled condition vocabulary for the monitoring form.
    """

    return await follow_up_service.list_monitoring_condition_options(db=db)


@router.get(
    "/reports/{report_reference}/follow-ups",
    response_model=FollowUpListResponse,
)
async def get_follow_ups(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
    include_superseded: bool = Query(
        default=False,
        description="Include records replaced by a later correction.",
    ),
):
    """
    US7.1 AC7. The follow-up history for an owned case, oldest first. An
    empty history is returned with a plain message rather than implied.
    """

    return await follow_up_service.list_follow_ups_for_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=current_coordinator["user_id"],
        include_superseded=include_superseded,
    )


@router.post(
    "/reports/{report_reference}/follow-ups",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_follow_up(
    report_reference: str,
    the_request: FollowUpCreate,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US7.1. Record an action (planned or taken) or a sourced external outcome.

    An action moves the case along the response chain. A sourced outcome
    never does, so a referral is not turned into a completed action (AC5).
    """

    return await follow_up_service.record_follow_up(
        db=db,
        report_reference=report_reference,
        coordinator_id=current_coordinator["user_id"],
        the_request=the_request,
    )


@router.get(
    "/reports/{report_reference}/follow-ups/{case_action_id}",
    response_model=FollowUpResponse,
)
async def get_follow_up(
    report_reference: str,
    case_action_id: int,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US7.1. One follow-up record with safe evidence metadata.
    """

    return await follow_up_service.get_follow_up_for_owned_case(
        db=db,
        report_reference=report_reference,
        case_action_id=case_action_id,
        coordinator_id=current_coordinator["user_id"],
    )


@router.patch(
    "/reports/{report_reference}/follow-ups/{case_action_id}",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def correct_follow_up(
    report_reference: str,
    case_action_id: int,
    the_request: FollowUpCorrection,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US7.1 AC8. Correct a follow-up by appending a superseding record.

    Returns 201 rather than 200 because a new record is created: follow-up
    history is append-only, so the original stays in place.
    """

    return await follow_up_service.correct_follow_up(
        db=db,
        report_reference=report_reference,
        case_action_id=case_action_id,
        coordinator_id=current_coordinator["user_id"],
        the_request=the_request,
    )


@router.post(
    "/reports/{report_reference}/monitoring",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_monitoring_record(
    report_reference: str,
    the_request: MonitoringCreate,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US7.2. Record a dated monitoring visit with a human-reviewed condition.

    The case status does not change: monitoring may repeat, and a visit may
    close with no next visit scheduled (AC2).
    """

    return await follow_up_service.record_monitoring(
        db=db,
        report_reference=report_reference,
        coordinator_id=current_coordinator["user_id"],
        the_request=the_request,
    )
