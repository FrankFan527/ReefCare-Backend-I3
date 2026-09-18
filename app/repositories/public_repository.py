from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_public_site(
    db: AsyncSession,
    dive_site_id: int,
):
    """
    Return the general public-safe identity of one dive site.

    Centre coordinates are included. They were excluded when this was written
    because every row held NULL, so exposing them would have offered a field
    that was never populated.

    A dive site centre is published reference data, the position of a named
    site that appears on any operator's listing. It is not a report location,
    which stays behind reefcare_report_location(). Returning it does not
    weaken the location privacy model.

    default_uncertainty_metres travels with the coordinate rather than being
    optional. A dive-site-only report is represented at the site centre with
    that radius, and a coordinate served without its radius invites a map pin
    claiming a precision nobody supplied.
    """

    result = await db.execute(
        text(
            """
            SELECT
                dive_site_id,
                name,
                public_area_label,
                region,

                centre_latitude,
                centre_longitude,
                default_uncertainty_metres

            FROM dive_site

            WHERE dive_site_id = :dive_site_id

            LIMIT 1
            """
        ),
        {
            "dive_site_id": dive_site_id,
        },
    )

    return result.mappings().first()


async def list_public_site_activity(
    db: AsyncSession,
    dive_site_id: int,
) -> list:
    """
    Return only explicitly approved/configured public-safe
    activity.

    Private reports are deliberately not queried here.
    """

    result = await db.execute(
        text(
            """
            SELECT
                public_activity_id,
                activity_type,
                title,
                summary,
                activity_date,
                source_label

            FROM public_reef_activity

            WHERE
                dive_site_id = :dive_site_id
                AND is_public = TRUE

            ORDER BY
                activity_date DESC NULLS LAST,
                display_order,
                public_activity_id DESC
            """
        ),
        {
            "dive_site_id": dive_site_id,
        },
    )

    return result.mappings().all()