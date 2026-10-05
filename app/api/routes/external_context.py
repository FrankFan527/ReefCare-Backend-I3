# ---------------------------------------------------------------------------
# US8.3 Selected external context — route.
#
# Mounted under /public. No authentication: the values are NOAA's own public
# data, and nothing ReefCare holds about a report is involved.
# ---------------------------------------------------------------------------

from fastapi import APIRouter

from app.api.dependencies.db import DatabaseSession
from app.schemas.external_context import ExternalContextResponse
from app.services import external_context_service


router = APIRouter()


@router.get(
    "/dive-sites/{dive_site_id}/external-context",
    response_model=ExternalContextResponse,
)
async def get_external_context(
    dive_site_id: int,
    db: DatabaseSession,
):
    """
    US8.3. NOAA Coral Reef Watch heat-stress context for one configured site:
    degree heating weeks and the bleaching alert level, each with the day it
    describes, when it was retrieved, and its source.

    Supplementary only. It never verifies, rejects, prioritises or closes a
    report (AC3). When NOAA cannot be reached, the most recent stored values
    are returned with their real dates, or the state is `unavailable`; the
    rest of ReefCare is unaffected either way (AC4).
    """

    return await external_context_service.get_external_context(
        db=db,
        dive_site_id=dive_site_id,
    )
