# ---------------------------------------------------------------------------
# Epic 9 public Reef-Aware Dive Planning routes.
#
# US9.1-US9.4 are public capabilities and intentionally
# have no authentication dependency.
#
# Current implementation:
#
# US9.1 Seasonal Calendar
# US9.2 Travel-Date Comparison
# US9.3 Dive-Site Comparison
# US9.4 AI Planning Brief
# ---------------------------------------------------------------------------

from datetime import date

from fastapi import (
    APIRouter,
    Query,
)

from app.api.dependencies.db import (
    DatabaseSession,
)
from app.schemas.planning import (
    DateComparisonResponse,
    PlanningBriefRequest,
    PlanningBriefResponse,
    SeasonalCalendarResponse,
    SiteComparisonResponse,
)
from app.services.planning_brief_service import (
    generate_planning_brief,
)
from app.services.planning_service import (
    compare_sites_for_date,
    compare_travel_dates,
    get_seasonal_calendar,
)


router = APIRouter()


@router.get(
    "/areas/{area_code}/seasonality",
    response_model=(
        SeasonalCalendarResponse
    ),
)
async def get_area_seasonality(
    area_code: str,
    db: DatabaseSession,
):
    """
    US9.1 public seasonal calendar.
    """

    return await get_seasonal_calendar(
        db=db,

        area_code=(
            area_code.lower()
        ),
    )


@router.get(
    "/areas/{area_code}/dates",
    response_model=(
        DateComparisonResponse
    ),
)
async def get_date_comparison(
    area_code: str,
    db: DatabaseSession,

    from_date: date = Query(
        alias="from",
    ),

    to_date: date = Query(
        alias="to",
    ),
):
    """
    US9.2 compare environmental forecast conditions across
    a travel window.
    """

    return await compare_travel_dates(
        db=db,

        area_code=(
            area_code.lower()
        ),

        from_date=from_date,
        to_date=to_date,
    )


@router.get(
    "/areas/{area_code}/sites",
    response_model=(
        SiteComparisonResponse
    ),
)
async def get_site_comparison(
    area_code: str,
    db: DatabaseSession,

    date_value: date = Query(
        alias="date",
    ),
):
    """
    US9.3 compare every supported site in the planning
    area for one selected date.
    """

    return await compare_sites_for_date(
        db=db,

        area_code=(
            area_code.lower()
        ),

        requested_date=(
            date_value
        ),
    )


@router.post(
    "/brief",
    response_model=(
        PlanningBriefResponse
    ),
)
async def create_planning_brief(
    brief_input: PlanningBriefRequest,
    db: DatabaseSession,
):
    """
    US9.4 generate an optional AI-written planning brief.

    The client supplies only site/date intent. Forecast and
    public reef context are resolved by the backend.

    AI failure is non-blocking and returns
    status="unavailable".
    """

    return await generate_planning_brief(
        db=db,

        site_id=(
            brief_input.site_id
        ),

        planned_date=(
            brief_input
            .planned_date
        ),
    )