# ---------------------------------------------------------------------------
# US8.1 Coordinator site history — routes.
#
# Mounted under /coordinator. Site-scoped context, deliberately separate from
# E5 Geospatial Hotspot Analysis, which answers a different question across
# areas and time (AC6).
# ---------------------------------------------------------------------------

from fastapi import APIRouter

from app.api.dependencies.authorization import CurrentCoordinator
from app.api.dependencies.db import DatabaseSession
from app.schemas.site_history import SiteHistoryResponse
from app.services import site_history_service


router = APIRouter()


@router.get(
    "/sites/{dive_site_id}/history",
    response_model=SiteHistoryResponse,
)
async def get_site_history(
    dive_site_id: int,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    US8.1. The recorded ReefCare history for one configured site:
    observations with the assessment state each has reached, and the dated
    E7 follow-up, monitoring and sourced-outcome records on them.

    Carries no descriptions, evidence, coordinates or Observer identity. A
    report reference is shown only for cases you own.

    Too little recorded history returns `insufficient_history` rather than
    implying the reef is healthy.
    """

    return await site_history_service.get_site_history(
        db=db,
        dive_site_id=dive_site_id,
        coordinator_id=current_coordinator["user_id"],
    )
