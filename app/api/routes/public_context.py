# ---------------------------------------------------------------------------
# US8.2 / US2.4 Reusable public-safe site context — route.
#
# Mounted under /public. No authentication: everything returned here has
# passed the E8 eligibility rule, and nothing report-level reaches it.
# ---------------------------------------------------------------------------

from fastapi import APIRouter

from app.api.dependencies.db import DatabaseSession
from app.schemas.public_context import PublicSiteContextResponse
from app.services import public_context_service


router = APIRouter()


@router.get(
    "/dive-sites/{dive_site_id}/context",
    response_model=PublicSiteContextResponse,
)
async def get_public_site_context(
    dive_site_id: int,
    db: DatabaseSession,
):
    """
    US8.2. The public-safe ReefCare context for one configured site:
    accepted threat categories with counts and month-level recency, a
    two-number assessment summary, and published conservation activity.

    Carries no report references, Observer identity, descriptions, evidence,
    precise coordinates, Coordinator identity or private closure detail.

    Returns `no_public_context` when nothing meets the eligibility rule. That
    is a statement about what has been reported, never about the reef.
    """

    return await public_context_service.get_public_site_context(
        db=db,
        dive_site_id=dive_site_id,
    )
