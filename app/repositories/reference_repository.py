# ---------------------------------------------------------------------------
# Read-only queries against canonical reference tables.
#
# Raw SQL remains inside the repository so routes and
# services do not own persistence/query details.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


async def list_active_threat_categories(
    db: AsyncSession,
) -> list:
    """
    Return threat categories currently selectable for a
    report.
    """

    result = await db.execute(
        text(
            """
            SELECT
                threat_category_id,
                code,
                label,
                short_explanation,
                useful_evidence,
                safety_reminder,
                icon_reference,

                -- F10. Returned even when null, so the interface can show
                -- that a fact has no recorded source rather than silently
                -- presenting it as though it did.
                source_reference,
                last_reviewed_at
            FROM threat_category

            WHERE
                is_selectable = TRUE

            ORDER BY
                display_order,
                threat_category_id
            """
        )
    )

    return result.mappings().all()


async def list_active_dive_sites(
    db: AsyncSession,
) -> list:
    """
    Return named dive sites that an observer may select.

    Centre coordinates are included. They were excluded in Iteration 1 for a
    reason that no longer holds: every row was NULL, so returning them would
    have offered a field that was never populated.

    A dive site centre is public reference data. It is the published position
    of a named site that appears on every operator's website, and it is a
    different thing from a report's precise location, which stays behind
    reefcare_report_location(). Returning a site centre does not weaken the
    location privacy model.

    default_uncertainty_metres travels with the coordinate rather than being
    optional. When an observer chooses dive-site-only, the report is
    represented at the site centre with that radius, and a coordinate served
    without its radius invites the interface to plot a point that claims a
    precision nobody supplied.

    is_verified is not used as a filter. It now means the coordinates have
    been sourced, and every row is true, so filtering would change nothing.
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

            ORDER BY
                public_area_label,
                name
            """
        )
    )

    return result.mappings().all()


async def get_selectable_threat_category(
    db: AsyncSession,
    threat_category_id: int,
):
    """
    Resolve a submitted threat-category ID to the
    canonical selectable reference row.
    """

    result = await db.execute(
        text(
            """
            SELECT
                threat_category_id,
                code,
                label

            FROM threat_category

            WHERE
                threat_category_id =
                    :threat_category_id

                AND is_selectable = TRUE

            LIMIT 1
            """
        ),
        {
            "threat_category_id":
                threat_category_id,
        },
    )

    return result.mappings().first()


async def get_location_confidence(
    db: AsyncSession,
    code: str,
):
    """
    Resolve a canonical location_confidence.code.
    """

    result = await db.execute(
        text(
            """
            SELECT
                location_confidence_id,
                code,
                label,
                uncertainty_metres

            FROM location_confidence

            WHERE
                code = :code

            LIMIT 1
            """
        ),
        {
            "code": code,
        },
    )

    return result.mappings().first()


async def get_location_source(
    db: AsyncSession,
    code: str,
):
    """
    Resolve a canonical location_source.code.
    """

    result = await db.execute(
        text(
            """
            SELECT
                location_source_id,
                code,
                label

            FROM location_source

            WHERE
                code = :code

            LIMIT 1
            """
        ),
        {
            "code": code,
        },
    )

    return result.mappings().first()


async def get_dive_site_location_reference(
    db: AsyncSession,
    dive_site_id: int,
):
    """
    Return the internal site location reference used for
    advisory selected-site versus precise-point checking.

    Centre coordinates are intentionally not returned by
    list_active_dive_sites().

    Missing centre coordinates are valid and cause the
    application to return checkAvailable=false.
    """

    result = await db.execute(
        text(
            """
            SELECT
                dive_site_id,
                name,
                public_area_label,
                centre_latitude,
                centre_longitude,
                default_uncertainty_metres,
                coordinate_source,
                is_verified

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