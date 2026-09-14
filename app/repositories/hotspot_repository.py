"""Read-only US5.6 SQL over the existing canonical schema.

Never join report_location/evidence or read descriptions, observer identifiers
or assessment notes.

A report's named dive site may supply a site-level reference centre for map
visualisation. The SQL generalises that centre before it leaves the repository.

Exact report coordinates are never read.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.hotspot import HotspotFilters


SITE_COLUMNS = """
    ds.dive_site_id AS site_id, ds.name AS site_name,
    ds.public_area_label AS area, ds.region
"""

# No one-to-many joins: one row per original report, even with multiple evidence
# files, decisions or events. All terminal statuses remain eligible for history.
BASE_CTE = """
WITH base AS NOT MATERIALIZED (
    SELECT r.report_id, r.report_reference, r.observed_at, r.submitted_at,
            r.claimed_by_user_id,
            COALESCE(tc.code, 'unsure') AS threat_code,
            COALESCE(tc.label, 'Unsure') AS threat_label,
            cs.code AS status_code, cs.internal_label AS status_label,
            cs.is_terminal AS is_closed,
            ds.dive_site_id AS site_id,
            ds.name AS site_name,
            ds.public_area_label AS area,
            ds.region,
            ROUND(
                ds.centre_latitude,
                2
            ) AS map_latitude,
            ROUND(
                ds.centre_longitude,
                2
            ) AS map_longitude,
            GREATEST(
                ds.default_uncertainty_metres,
                1000
            ) AS map_uncertainty_metres
    FROM report r
    JOIN case_status cs ON cs.case_status_id = r.current_status_id
    LEFT JOIN threat_category tc ON tc.threat_category_id = r.threat_category_id
    LEFT JOIN dive_session dsn ON dsn.dive_session_id = r.dive_session_id
    LEFT JOIN dive_site ds ON ds.dive_site_id = dsn.dive_site_id
    WHERE r.deleted_at IS NULL
      AND r.submitted_at IS NOT NULL
      AND cs.code <> 'draft'
      AND (CAST(:site_id AS bigint) IS NULL OR ds.dive_site_id = :site_id)
      AND (CAST(:area AS text) IS NULL OR ds.public_area_label = :area)
      AND (CAST(:region AS text) IS NULL OR ds.region = :region)
      AND (CAST(:threat AS text) IS NULL OR COALESCE(tc.code, 'unsure') = :threat)
), filtered AS (
    SELECT * FROM base
    WHERE observed_at >= :start_at AND observed_at < :end_at
), usable AS (
    SELECT * FROM filtered
    WHERE site_id IS NOT NULL AND NULLIF(BTRIM(site_name), '') IS NOT NULL
)
"""


def filter_parameters(filters: HotspotFilters) -> dict:
    tz = ZoneInfo(filters.timezone)
    return {
        "site_id": filters.site_id,
        "area": filters.area,
        "region": filters.region,
        "threat": filters.threat.value if filters.threat else None,
        "start_at": datetime.combine(filters.observed_from, time.min, tz),
        "end_at": datetime.combine(filters.observed_to + timedelta(days=1), time.min, tz),
        "timezone": filters.timezone,
        "interval": filters.interval,
    }


async def list_sites(db: AsyncSession):
    result = await db.execute(text(f"""
        SELECT {SITE_COLUMNS}
        FROM dive_site ds
        WHERE NULLIF(BTRIM(ds.name), '') IS NOT NULL
        ORDER BY ds.public_area_label NULLS LAST, ds.name, ds.dive_site_id
    """))
    return result.mappings().all()


async def get_analysis(db: AsyncSession, filters: HotspotFilters):
    # Counts and buckets share one statement/MVCC snapshot. Results cannot
    # disagree because a report arrived between separate count/map queries.
    result = await db.execute(text(BASE_CTE + """
    , grouped AS (
        SELECT
            site_id,
            site_name,
            area,
            region,

            map_latitude,
            map_longitude,
            map_uncertainty_metres,

            threat_code,
            threat_label,

            date_trunc(
                :interval,
                observed_at
                    AT TIME ZONE :timezone
            )::date AS bucket,

            COUNT(*) AS report_count
        FROM usable
        GROUP BY
            site_id,
            site_name,
            area,
            region,

            map_latitude,
            map_longitude,
            map_uncertainty_metres,

            threat_code,
            threat_label,
            bucket
    )
    SELECT (SELECT COUNT(*) FROM filtered) AS matching_report_count,
           (SELECT COUNT(*) FROM usable) AS included_report_count,
           (SELECT COUNT(*) FROM base WHERE observed_at IS NULL) AS undated_report_count,
           COALESCE((SELECT jsonb_agg(to_jsonb(g) ORDER BY site_id, bucket, threat_code)
                     FROM grouped g), '[]'::jsonb) AS groups,
           statement_timestamp() AS analysed_at
    """), filter_parameters(filters))
    return result.mappings().one()


async def list_reports(db: AsyncSession, filters: HotspotFilters, page: int, page_size: int):
    params = filter_parameters(filters)
    params.update(limit=page_size, offset=(page - 1) * page_size)
    result = await db.execute(text(BASE_CTE + """
    , page_rows AS (
        SELECT p.report_reference, p.site_id, p.site_name, p.area, p.region,
               p.threat_code, p.threat_label, p.observed_at, p.submitted_at,
               p.status_code, p.status_label, p.is_closed, p.claimed_by_user_id,
               u.display_name AS owner_display_name
        FROM usable p
        LEFT JOIN app_user u ON u.user_id = p.claimed_by_user_id
        ORDER BY p.observed_at DESC, p.report_id DESC
        LIMIT :limit OFFSET :offset
    )
    SELECT (SELECT COUNT(*) FROM usable) AS total,
           COALESCE((SELECT jsonb_agg(to_jsonb(p)) FROM page_rows p), '[]'::jsonb) AS items
    """), params)
    return result.mappings().one()


async def get_intake(db: AsyncSession, report_reference: str):
    result = await db.execute(text(f"""
        SELECT r.report_reference, r.observed_at, r.submitted_at,
               r.claimed_by_user_id, {SITE_COLUMNS},
               COALESCE(tc.code, 'unsure') AS threat_code,
               COALESCE(tc.label, 'Unsure') AS threat_label,
               cs.code AS status_code, cs.internal_label AS status_label,
               cs.is_terminal AS is_closed,
               u.display_name AS owner_display_name
        FROM report r
        JOIN case_status cs ON cs.case_status_id = r.current_status_id
        LEFT JOIN threat_category tc ON tc.threat_category_id = r.threat_category_id
        LEFT JOIN dive_session dsn ON dsn.dive_session_id = r.dive_session_id
        LEFT JOIN dive_site ds ON ds.dive_site_id = dsn.dive_site_id
        LEFT JOIN app_user u ON u.user_id = r.claimed_by_user_id
        WHERE r.report_reference = :reference AND r.deleted_at IS NULL
          AND r.submitted_at IS NOT NULL AND cs.code <> 'draft'
    """), {"reference": report_reference})
    return result.mappings().first()


async def get_owned_context(db: AsyncSession, report_reference: str, coordinator_id: int):
    # Ownership is a SQL predicate; no protected case aggregate is fetched.
    result = await db.execute(text(f"""
        SELECT r.report_reference, r.observed_at, {SITE_COLUMNS}
        FROM report r
        JOIN case_status cs ON cs.case_status_id = r.current_status_id
        LEFT JOIN dive_session dsn ON dsn.dive_session_id = r.dive_session_id
        LEFT JOIN dive_site ds ON ds.dive_site_id = dsn.dive_site_id
        WHERE r.report_reference = :reference AND r.claimed_by_user_id = :coordinator_id
          AND r.deleted_at IS NULL AND r.submitted_at IS NOT NULL AND cs.code <> 'draft'
    """), {"reference": report_reference, "coordinator_id": coordinator_id})
    return result.mappings().first()