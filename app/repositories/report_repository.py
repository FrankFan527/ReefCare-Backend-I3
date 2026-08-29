from typing import Any

from datetime import date

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession


_submit_report_statement = text(
    """
    SELECT reefcare_submit_report(
        p_observer_id =>
            CAST(:observer_id AS bigint),

        p_dive_session_id =>
            CAST(:dive_session_id AS bigint),

        p_threat_category_code =>
            CAST(:threat_category_code AS text),

        p_description =>
            CAST(:description AS text),

        p_observed_at =>
            CAST(:observed_at AS timestamptz),

        p_location_source_code =>
            CAST(:location_source_code AS text),

        p_location_confidence_code =>
            CAST(:location_confidence_code AS text),

        p_evidence =>
            CAST(:evidence AS jsonb),

        p_estimated_depth_metres =>
            CAST(:estimated_depth_metres AS numeric),

        p_latitude =>
            CAST(:latitude AS numeric),

        p_longitude =>
            CAST(:longitude AS numeric),

        p_relocation_notes =>
            CAST(:relocation_notes AS text)
    ) AS report_reference
    """
).bindparams(
    bindparam(
        "evidence",
        type_=JSONB,
    )
)


async def submit_report(
    db: AsyncSession,
    *,
    observer_id: int,
    dive_session_id: int,
    threat_category_code: str,
    description: str,
    observed_at,
    location_source_code: str,
    location_confidence_code: str,
    evidence: list[dict[str, Any]],
    estimated_depth_metres: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    relocation_notes: str | None = None,
) -> str:
    """
    Submit a complete report through the canonical
    PostgreSQL reefcare_submit_report() function.

    PostgreSQL atomically creates:
    - report_location
    - report
    - evidence rows
    - submitted case_event
    - automatic received status event

    This repository does not commit the transaction.
    Transaction ownership belongs to the service layer.
    """

    result = await db.execute(
        _submit_report_statement,
        {
            "observer_id":
                observer_id,

            "dive_session_id":
                dive_session_id,

            "threat_category_code":
                threat_category_code,

            "description":
                description,

            "observed_at":
                observed_at,

            "location_source_code":
                location_source_code,

            "location_confidence_code":
                location_confidence_code,

            "evidence":
                evidence,

            "estimated_depth_metres":
                estimated_depth_metres,

            "latitude":
                latitude,

            "longitude":
                longitude,

            "relocation_notes":
                relocation_notes,
        },
    )

    return result.scalar_one()

async def get_submission_confirmation(
    db: AsyncSession,
    *,
    report_reference: str,
    observer_id: int,
):
    """
    Return the post-submission data required by the
    ReportSubmittedResponse.

    The observer_id condition prevents this helper from
    returning another observer's report.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                cs.code AS status,

                r.submitted_at,

                COALESCE(
                    ds.name,
                    ds.public_area_label,
                    'Location not specified'
                ) AS general_location

            FROM report r

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            WHERE r.report_reference =
                  :report_reference

              AND r.observer_id =
                  :observer_id

              AND r.deleted_at IS NULL

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "observer_id":
                observer_id,
        },
    )

    return result.mappings().first()

async def get_owned_dive_session(
    db: AsyncSession,
    *,
    dive_session_id: int,
    observer_id: int,
):
    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.dive_site_id,
                ds.observer_id
            FROM dive_session ds
            WHERE ds.dive_session_id = :dive_session_id
              AND ds.observer_id = :observer_id
            LIMIT 1
            """
        ),
        {
            "dive_session_id": dive_session_id,
            "observer_id": observer_id,
        },
    )

    return result.mappings().first()


async def list_my_reports(
    db: AsyncSession,
    *,
    observer_id: int,
    status_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
):
    """
    Return one observer's My Reports list through the database-owned
    reefcare_my_reports(observer_id) scope.

    The join back to report/case_status is only used to obtain the
    canonical status code required by the API and to apply optional
    filters. The candidate report set always starts from the
    observer-scoped PostgreSQL function.
    """

    offset = (page - 1) * page_size

    filter_sql = """
        WHERE (
            CAST(:status_code AS text) IS NULL
            OR cs.code = CAST(:status_code AS text)
        )
        AND (
            CAST(:from_date AS date) IS NULL
            OR m.submitted_at >= CAST(:from_date AS date)
        )
        AND (
            CAST(:to_date AS date) IS NULL
            OR m.submitted_at <
               CAST(:to_date AS date) + INTERVAL '1 day'
        )
    """

    result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *
                FROM reefcare_my_reports(
                    CAST(:observer_id AS bigint)
                )
            )
            SELECT
                m.report_reference,
                m.threat,
                m.area,
                cs.code AS status,
                m.status_label,
                m.closure_label,
                m.submitted_at

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            {filter_sql}

            ORDER BY
                m.submitted_at DESC,
                m.report_reference DESC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "observer_id": observer_id,
            "status_code": status_code,
            "from_date": from_date,
            "to_date": to_date,
            "limit": page_size,
            "offset": offset,
        },
    )

    rows = result.mappings().all()

    count_result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *
                FROM reefcare_my_reports(
                    CAST(:observer_id AS bigint)
                )
            )
            SELECT count(*)

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            {filter_sql}
            """
        ),
        {
            "observer_id": observer_id,
            "status_code": status_code,
            "from_date": from_date,
            "to_date": to_date,
        },
    )

    total = count_result.scalar_one()

    return rows, total


async def get_my_report(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return one observer-owned report from an observer-scoped query path.

    reefcare_my_reports(observer_id) is the first relation in the query,
    so a reference belonging to another observer cannot enter this
    projection. Only observer-safe request/closure notes are selected;
    coordinator identity and case-decision internals are not returned.
    """

    result = await db.execute(
        text(
            """
            WITH mine AS (
                SELECT *
                FROM reefcare_my_reports(
                    CAST(:observer_id AS bigint)
                )
                WHERE report_reference =
                      :report_reference
            )
            SELECT
                m.report_reference,
                m.threat,
                m.area,

                cs.code AS status,
                m.status_label,
                m.closure_label,

                r.observed_at,
                r.estimated_depth_metres,
                r.description,
                r.submitted_at,
                ds.name AS dive_site_name,

                CASE
                    WHEN cs.code =
                         'needs_more_info'
                    THEN info_event.note
                    ELSE NULL
                END AS information_request_reason,

                CASE
                    WHEN cs.is_terminal
                    THEN close_event.note
                    ELSE NULL
                END AS public_closure_note

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN LATERAL (
                SELECT e.note
                FROM case_event e
                JOIN case_status event_status
                    ON event_status.case_status_id =
                       e.to_status_id
                WHERE e.report_id =
                      r.report_id
                  AND event_status.code =
                      'needs_more_info'
                  AND e.note IS NOT NULL
                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC
                LIMIT 1
            ) info_event ON TRUE

            LEFT JOIN LATERAL (
                SELECT e.note
                FROM case_event e
                WHERE e.report_id =
                      r.report_id
                  AND e.event_type =
                      'closed'
                  AND e.note IS NOT NULL
                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC
                LIMIT 1
            ) close_event ON TRUE

            LIMIT 1
            """
        ),
        {
            "observer_id": observer_id,
            "report_reference": (
                report_reference
            ),
        },
    )

    return result.mappings().first()


async def get_report_timeline(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return deterministic observer-facing status history through the
    canonical reefcare_report_timeline(reference, observer_id) function.
    """

    result = await db.execute(
        text(
            """
            SELECT
                status_label,
                occurred_at
            FROM reefcare_report_timeline(
                CAST(:report_reference AS text),
                CAST(:observer_id AS bigint)
            )
            """
        ),
        {
            "observer_id": observer_id,
            "report_reference": (
                report_reference
            ),
        },
    )

    return result.mappings().all()