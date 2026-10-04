from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_public_site(
    db: AsyncSession,
    dive_site_id: int,
):
    """
    Return the public-safe identity of one named dive site.

    The published site centre is reference data rather than
    a report's precise observation location.

    planning_area_code is the canonical E2 -> E9 mapping.
    A null value means ReefCare planning is not currently
    configured for this site. No area is guessed from
    labels or neighbouring sites.
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
                default_uncertainty_metres,

                planning_area_code

            FROM dive_site

            WHERE
                dive_site_id = :dive_site_id

            LIMIT 1
            """
        ),
        {
            "dive_site_id":
                dive_site_id,
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

    Iteration 3 note:
    E2 US2.4 will later consume the shared E8 public-safe
    site-context boundary. Until that E8 service is ready,
    this existing I2 projection remains unchanged.
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
            "dive_site_id":
                dive_site_id,
        },
    )

    return result.mappings().all()