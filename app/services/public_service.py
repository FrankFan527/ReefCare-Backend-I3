from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.public_repository import (
    get_public_site,
    list_public_site_activity,
)


async def get_public_activity(
    *,
    db: AsyncSession,
    dive_site_id: int,
) -> dict:
    """
    Build the public-safe activity projection for one site.

    An empty activity list is a valid state and must never
    be interpreted as proof that the site has no reef
    threats.
    """

    site = await get_public_site(
        db=db,
        dive_site_id=dive_site_id,
    )

    if site is None:
        raise NotFoundError(
            "Dive site not found"
        )

    rows = await list_public_site_activity(
        db=db,
        dive_site_id=dive_site_id,
    )

    items = [
        {
            "activity_id":
                row["public_activity_id"],

            "activity_type":
                row["activity_type"],

            "title":
                row["title"],

            "summary":
                row["summary"],

            "activity_date":
                row["activity_date"],

            "source_label":
                row["source_label"],
        }
        for row in rows
    ]

    if items:
        message = (
            "Public-safe ReefCare activity is available "
            "for this site."
        )

    else:
        message = (
            "No public ReefCare activity is currently "
            "available for this site."
        )

    return {
        "dive_site_id":
            site["dive_site_id"],

        "dive_site_name":
            site["name"],

        "public_area_label":
            site["public_area_label"],

        "has_activity":
            bool(items),

        "items":
            items,

        "message":
            message,
    }


async def build_report_handoff(
    *,
    db: AsyncSession,
    dive_site_id: int,
) -> dict:
    """
    Validate a public selected site and return the canonical
    handoff context for E2 -> authentication -> E4.

    No draft or private report is created here.
    """

    site = await get_public_site(
        db=db,
        dive_site_id=dive_site_id,
    )

    if site is None:
        raise NotFoundError(
            "Dive site not found"
        )

    return {
        "selected_dive_site_id":
            site["dive_site_id"],

        "selected_dive_site_name":
            site["name"],

        "public_area_label":
            site["public_area_label"],

        "requires_authentication":
            True,

        "reporting_path":
            "/reports/new",
    }