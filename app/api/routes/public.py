from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.api.dependencies.db import (
    DatabaseSession,
)
from app.core.exceptions import (
    NotFoundError,
)
from app.schemas.public import (
    PublicDiveSiteResponse,
    PublicReportHandoffResponse,
    PublicSiteActivityResponse,
)
from app.services.public_service import (
    build_report_handoff,
    get_public_activity,
    get_public_site_detail,
)


router = APIRouter()


@router.get(
    "/dive-sites/{dive_site_id}",
    response_model=PublicDiveSiteResponse,
)
async def get_public_dive_site(
    dive_site_id: int,
    db: DatabaseSession,
):
    """
    E2 public dive-site information.

    No authentication is required.

    planningAreaCode is the canonical E2 -> E9 planning
    handoff. A null value means this site is not currently
    configured for ReefCare planning.
    """

    try:
        result = await get_public_site_detail(
            db=db,
            dive_site_id=dive_site_id,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return PublicDiveSiteResponse(
        **result
    )


@router.get(
    "/dive-sites/{dive_site_id}/activity",
    response_model=PublicSiteActivityResponse,
)
async def get_site_activity(
    dive_site_id: int,
    db: DatabaseSession,
):
    """
    Public-safe ReefCare activity for a named dive site.

    Authentication is deliberately not required.

    This route never reads raw private report details.
    """

    try:
        result = await get_public_activity(
            db=db,
            dive_site_id=dive_site_id,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return PublicSiteActivityResponse(
        **result
    )


@router.get(
    "/dive-sites/{dive_site_id}/report-handoff",
    response_model=PublicReportHandoffResponse,
)
async def get_report_handoff(
    dive_site_id: int,
    db: DatabaseSession,
):
    """
    Validate the selected public dive site before entering
    the authenticated reporting workflow.

    The frontend keeps selectedDiveSiteId while redirecting
    through login/registration.
    """

    try:
        result = await build_report_handoff(
            db=db,
            dive_site_id=dive_site_id,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return PublicReportHandoffResponse(
        **result
    )