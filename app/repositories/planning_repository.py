# ---------------------------------------------------------------------------
# Epic 9 planning repository.
#
# Current production data layer:
#
# planning_area
#   area_code
#   area_label
#   query_latitude
#   query_longitude
#   site_count
#   notes
#
# area_daily_conditions
#   historical raw Open-Meteo values
#
# Historical condition rows are deliberately not used as
# future forecast values.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


async def get_planning_area(
    db: AsyncSession,
    area_code: str,
) -> dict | None:
    """
    Return one canonical E9 planning area.
    """

    result = await db.execute(
        text(
            """
            SELECT
                area_code,
                area_label,
                query_latitude,
                query_longitude,
                site_count,
                notes

            FROM planning_area

            WHERE
                area_code = :area_code

            LIMIT 1
            """
        ),
        {
            "area_code":
                area_code,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(row)


async def list_planning_sites(
    db: AsyncSession,
    area_label: str,
) -> list[dict]:
    """
    Return ReefCare dive sites configured under one
    planning-area public label.

    The current production schema has no explicit FK from
    dive_site to planning_area.

    Until the shared data layer adds that mapping, this
    query uses an exact match:

        dive_site.public_area_label
        =
        planning_area.area_label

    This is intentionally strict. A fuzzy match could hide
    incorrect reference data and assign a site to the wrong
    planning area.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_site_id,
                ds.name,
                ds.public_area_label,
                ds.region,

                ds.centre_latitude,
                ds.centre_longitude,
                ds.default_uncertainty_metres,

                ds.coordinate_source,
                ds.is_verified

            FROM dive_site AS ds

            WHERE
                ds.public_area_label =
                    :area_label

            ORDER BY
                ds.name,
                ds.dive_site_id
            """
        ),
        {
            "area_label":
                area_label,
        },
    )

    return [
        dict(row)
        for row
        in result.mappings().all()
    ]


async def get_historical_condition_coverage(
    db: AsyncSession,
    area_code: str,
) -> dict | None:
    """
    Return history coverage metadata only.

    This is useful for future provenance/model work but is
    never used as a substitute for a live forecast.
    """

    result = await db.execute(
        text(
            """
            SELECT
                area_code,
                MIN(observation_date)
                    AS first_observation_date,
                MAX(observation_date)
                    AS last_observation_date,
                COUNT(*)
                    AS observation_count

            FROM area_daily_conditions

            WHERE
                area_code = :area_code

            GROUP BY
                area_code
            """
        ),
        {
            "area_code":
                area_code,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(row)