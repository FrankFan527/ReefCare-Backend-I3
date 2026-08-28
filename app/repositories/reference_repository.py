# ---------------------------------------------------------------------------
# Read-only queries against the reference tables.
#
# Follows the pattern already used in queue_service and case_service: raw SQL
# through text(), no ORM models. Keeping the SQL here rather than in the route
# means the route stays a thin HTTP adapter.
# ---------------------------------------------------------------------------
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_active_dive_sites(db: AsyncSession) -> list:
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

    the_dive_site_result = await db.execute(
        text(
            """
            SELECT
                dive_site_id,
                name,
                public_area_label,
                region
            FROM dive_site
            ORDER BY public_area_label, name
            """
        )
    )

    return the_dive_site_result.mappings().all()