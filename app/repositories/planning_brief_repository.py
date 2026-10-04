# ---------------------------------------------------------------------------
# US9.4 Planning Brief reference queries.
#
# This repository resolves the selected dive site to its
# canonical Epic 9 planning area.
#
# The current production schema has no explicit
# planning_area <-> dive_site relation.
#
# Until that shared mapping exists, the integration uses
# the exact public label relationship already used by the
# Epic 9 planning backend:
#
#     dive_site.public_area_label
#     =
#     planning_area.area_label
#
# No private report or Observer data is queried here.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


async def get_planning_context_for_site(
    db: AsyncSession,
    dive_site_id: int,
):
    """
    Resolve one public dive site to its canonical planning
    area.

    Returns None when the site does not exist or when its
    public area label has no configured planning area.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_site_id,
                ds.name
                    AS dive_site_name,
                ds.public_area_label,

                pa.area_code,
                pa.area_label

            FROM dive_site AS ds

            JOIN planning_area AS pa
                ON pa.area_label =
                   ds.public_area_label

            WHERE
                ds.dive_site_id =
                    :dive_site_id

            LIMIT 1
            """
        ),
        {
            "dive_site_id":
                dive_site_id,
        },
    )

    return (
        result
        .mappings()
        .first()
    )