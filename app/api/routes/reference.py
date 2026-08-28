# ---------------------------------------------------------------------------
# Reference data routes (US4.1).
#
# Any authenticated user may read this list. It carries no coordinates, and a
# coordinator reviewing a case needs the same site names an observer sees, so
# restricting it to observers would block a legitimate read for no benefit.
# ---------------------------------------------------------------------------
from fastapi import APIRouter

from app.api.dependencies.auth import CurrentUserClaims
from app.api.dependencies.db import DatabaseSession
from app.schemas.reference import DiveSiteResponse
from app.repositories.reference_repository import list_active_dive_sites


router = APIRouter()


@router.get(
    "/dive-sites",
    response_model=list[DiveSiteResponse],
)
async def get_dive_sites(
    current_user: CurrentUserClaims,
    db: DatabaseSession,
):
    """Return the named dive sites available for the location step."""

    the_dive_site_rows = await list_active_dive_sites(db=db)

    return [
        DiveSiteResponse(**dict(the_single_row))
        for the_single_row in the_dive_site_rows
    ]