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

        # Published site centre, returned so the public map plots the real
        # position rather than a hardcoded one. Nullable: a site added later
        # may not have been sourced, and an absent coordinate is a truthful
        # answer rather than a gap to fill.
        "centre_latitude":
            site["centre_latitude"],

        "centre_longitude":
            site["centre_longitude"],

        # Returned with the coordinate, never without it. This is the radius a
        # dive-site-only report actually covers.
        "default_uncertainty_metres":
            site["default_uncertainty_metres"],

        "requires_authentication":
            True,

        # F11. The frontend route is /report-a-reef; /reports/new was never a
        # real path, so the handoff was sending visitors nowhere. Confirmed
        # with the frontend owner on 17 September 2026.
        "reporting_path":
            "/report-a-reef",
    }