# ---------------------------------------------------------------------------
# US5.9 Related Incidents — Coordinator routes (normal E5, Miusan).
#
# Mounted under /coordinator. Routes stay thin: authentication and the
# coordinator role come from CurrentCoordinator, everything else is in
# related_incident_service.py.
#
# Paths use reportReference (RC-0001), like the rest of the I2 coordinator
# API, never an internal id.
# ---------------------------------------------------------------------------

from fastapi import APIRouter, status

from app.api.dependencies.authorization import CurrentCoordinator
from app.api.dependencies.db import DatabaseSession
from app.schemas.related_incident import (
    RejectionReasonOption,
    RelatedReportsResponse,
    RelationshipDecisionCreate,
    RelationshipDecisionResponse,
    ReportComparisonResponse,
)
from app.services import related_incident_service


router = APIRouter()


@router.get(
    "/reports/{report_reference}/related-reports",
    response_model=RelatedReportsResponse,
)
async def get_related_reports(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US5.9 AC3/AC4/AC9. Potentially Related Reports for a report you have
    claimed. Only Unclaimed or Owned-by-you candidates are returned, with no
    descriptions, evidence or coordinates. If the analysis failed or has not
    run, analysisState is "unavailable" (never "no matches").
    """

    return await related_incident_service.get_related_reports(
        db=db,
        report_reference=report_reference,
        coordinator_id=current_coordinator["user_id"],
    )


@router.post(
    "/reports/{report_reference}/related-reports/{candidate_reference}/claim-and-compare",
    response_model=ReportComparisonResponse,
)
async def claim_and_compare(
    report_reference: str,
    candidate_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US5.9 AC5. Claim an Unclaimed candidate, then open the comparison.
    409 if another Coordinator claimed it first.
    """

    return await related_incident_service.claim_and_compare(
        db=db,
        report_reference=report_reference,
        candidate_reference=candidate_reference,
        coordinator_id=current_coordinator["user_id"],
    )


@router.get(
    "/reports/{report_reference}/related-reports/{candidate_reference}/compare",
    response_model=ReportComparisonResponse,
)
async def compare_reports(
    report_reference: str,
    candidate_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US5.9 AC6. Side-by-side comparison. Both reports must be owned by you.
    """

    return await related_incident_service.compare_reports(
        db=db,
        report_reference=report_reference,
        candidate_reference=candidate_reference,
        coordinator_id=current_coordinator["user_id"],
    )


@router.post(
    "/reports/{report_reference}/related-reports/{candidate_reference}/decision",
    response_model=RelationshipDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_relationship_decision(
    report_reference: str,
    candidate_reference: str,
    the_request: RelationshipDecisionCreate,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US5.9 AC6/AC7. Confirm Same Incident or Not Related. Both reports must
    be owned by you. Never changes status, owner, evidence or closure (AC8).
    """

    return await related_incident_service.record_relationship_decision(
        db=db,
        report_reference=report_reference,
        candidate_reference=candidate_reference,
        coordinator_id=current_coordinator["user_id"],
        the_request=the_request,
    )


@router.get(
    "/related-reports/rejection-reasons",
    response_model=list[RejectionReasonOption],
)
async def get_rejection_reasons(
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Not Related reason options for the decision dialog.
    """

    return await related_incident_service.list_rejection_reason_options(db=db)
