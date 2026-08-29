# ---------------------------------------------------------------------------
# Read-only queries against the reference tables.
#
# Follows the pattern already used in queue_service and case_service: raw SQL
# through text(), no ORM models. Keeping the SQL here rather than in the route
# means the route stays a thin HTTP adapter.
# ---------------------------------------------------------------------------
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_active_threat_categories(
    db: AsyncSession,
) -> list:
    """
    Return the threat categories currently selectable
    for an Iteration 1 report.
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
                icon_reference
            FROM threat_category
            WHERE is_selectable = TRUE
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
    Return the named dive sites an observer may select from.

    No is_verified filter is applied. That column currently carries two
    conflicting meanings: the schema comment defines false as "community
    suggested, awaiting review", while the reference seed sets every row to
    false because centre coordinates have not yet been sourced from
    OpenStreetMap. Every seeded site is a genuine curated Malaysian dive
    site, so filtering on it would return an empty list and break the
    location step. Revisit when the site-suggestion queue lands in
    Iteration 2.

    No coordinate columns are selected, so a precise position cannot leak
    through this endpoint even if the schema changes later.
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
    canonical database reference row.

    Returns None if the category does not exist or
    cannot currently be selected.
    """

    result = await db.execute(
        text(
            """
            SELECT
                threat_category_id,
                code,
                label
            FROM threat_category
            WHERE threat_category_id = :threat_category_id
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
    Resolve a location_confidence.code.

    Returns None if the code is not defined in the
    canonical reference table.
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
            WHERE code = :code
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
    Resolve a location_source.code.

    Normally the report service derives the source
    from whether the observer supplied a map pin,
    but this helper is useful for validation/testing.
    """

    result = await db.execute(
        text(
            """
            SELECT
                location_source_id,
                code,
                label
            FROM location_source
            WHERE code = :code
            LIMIT 1
            """
        ),
        {
            "code": code,
        },
    )

    return result.mappings().first()