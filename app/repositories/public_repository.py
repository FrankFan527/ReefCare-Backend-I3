from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_public_site(
    db: AsyncSession,
    dive_site_id: int,
):
    """
    Return the general public-safe identity of one dive site.

    No centre coordinates are exposed.
    """

    result = await db.execute(
        text(
            """
            SELECT
                dive_site_id,
                name,
                public_area_label,
                region

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