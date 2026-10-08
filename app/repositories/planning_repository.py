# ---------------------------------------------------------------------------
# Epic 9 planning repository.
#
# Canonical area/site relationship:
#
#     dive_site.planning_area_code
#         ->
#     planning_area.area_code
#
# E2 and E9 therefore reuse the same dive_site record.
# Display labels are never used as relational keys.
#
# Historical area_daily_conditions rows remain factual
# history and are never substituted for live forecast data.
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
    area_code: str,
) -> list[dict]:
    """
    Return canonical ReefCare dive sites configured under
    one E9 planning area.

    Iteration 3 uses the explicit mapping:

        dive_site.planning_area_code
        =
        planning_area.area_code

    No site is inferred from public_area_label.
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
                ds.is_verified,

                ds.planning_area_code

            FROM dive_site AS ds

            WHERE
                ds.planning_area_code =
                    :area_code

            ORDER BY
                ds.name,
                ds.dive_site_id
            """
        ),
        {
            "area_code":
                area_code,
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

    This is useful for provenance/model work but is never
    used as a substitute for a live forecast.
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

async def list_seasonal_references(
    db: AsyncSession,
    area_code: str,
) -> list[dict]:
    """
    Return the reviewed US9.1 seasonal reference rows for
    one planning area, one row per calendar month at most.

    Months without a row stay unreviewed in the service.
    """

    result = await db.execute(
        text(
            """
            SELECT
                calendar_month,
                season_label,
                typical_conditions,
                favourability,
                basis_source,
                source_url,
                last_reviewed_at

            FROM seasonal_condition_reference

            WHERE
                area_code = :area_code

            ORDER BY
                calendar_month
            """
        ),
        {
            "area_code":
                area_code,
        },
    )

    return [
        dict(row)

        for row
        in result.mappings().all()
    ]
