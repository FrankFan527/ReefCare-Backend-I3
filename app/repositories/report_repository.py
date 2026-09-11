from datetime import date
from typing import Any

from sqlalchemy import (
    bindparam,
    text,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


# ---------------------------------------------------------------------------
# Report submission.
#
# PostgreSQL reefcare_submit_report() is the authoritative write path for a
# completed report. Python validates the request and reference data first,
# then passes the canonical values into this function.
# ---------------------------------------------------------------------------

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
    evidence: list[
        dict[str, Any]
    ],
    estimated_depth_metres: (
        float | None
    ) = None,
    latitude: (
        float | None
    ) = None,
    longitude: (
        float | None
    ) = None,
    relocation_notes: (
        str | None
    ) = None,
) -> str:
    """
    Submit a complete report through the canonical
    PostgreSQL reefcare_submit_report() function.
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
    Return the immediate confirmation projection for the
    submitting Observer.

    This keeps the established Iteration 1 contract:
    report reference, current status, timestamp and general
    location.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                cs.code
                    AS status,

                r.submitted_at,

                COALESCE(
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

            WHERE
                r.report_reference =
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
    """
    Return a dive session only when it belongs to the
    authenticated Observer.

    The ownership condition is applied in SQL so a session
    belonging to another user is never loaded into the
    service layer.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.dive_site_id,
                ds.observer_id

            FROM dive_session ds

            WHERE
                ds.dive_session_id =
                    :dive_session_id

                AND ds.observer_id =
                    :observer_id

            LIMIT 1
            """
        ),
        {
            "dive_session_id":
                dive_session_id,

            "observer_id":
                observer_id,
        },
    )

    return result.mappings().first()


# ---------------------------------------------------------------------------
# Observer report tracking (US6.1 / US6.2).
#
# reefcare_my_reports(observer_id) remains the primary ownership boundary.
# The extra joins below only enrich rows that have already been scoped to the
# authenticated Observer.
#
# No coordinator identity, internal decision field or private evidence object
# reference is selected.
# ---------------------------------------------------------------------------


async def list_my_reports(
    db: AsyncSession,
    *,
    observer_id: int,
    status_code: (
        str | None
    ) = None,
    from_date: (
        date | None
    ) = None,
    to_date: (
        date | None
    ) = None,
    page: int = 1,
    page_size: int = 20,
):
    """
    Return one Observer's reports with richer Iteration 2
    tracking information.

    reefcare_my_reports() already provides:
    - ownership scope
    - threat label
    - general location
    - Observer-safe status label
    - Observer-safe closure label
    - submitted timestamp

    This query enriches those safe rows with:
    - canonical status code
    - observed timestamp
    - dive-site name
    - last workflow update timestamp
    """

    offset = (
        (page - 1)
        * page_size
    )

    filter_sql = """
        WHERE (
            CAST(:status_code AS text) IS NULL
            OR cs.code =
               CAST(:status_code AS text)
        )

        AND (
            CAST(:from_date AS date) IS NULL
            OR m.submitted_at >=
               CAST(:from_date AS date)
        )

        AND (
            CAST(:to_date AS date) IS NULL
            OR m.submitted_at <
               CAST(:to_date AS date)
               + INTERVAL '1 day'
        )
    """

    result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )
            )

            SELECT
                m.report_reference,
                m.threat,
                m.area,

                r.observed_at,

                ds.name
                    AS dive_site_name,

                cs.code
                    AS status,

                m.status_label,
                m.closure_label,

                m.submitted_at,

                COALESCE(
                    latest_event.occurred_at,
                    m.submitted_at
                ) AS last_updated_at

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

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
                SELECT
                    e.occurred_at

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) latest_event
                ON TRUE

            {filter_sql}

            ORDER BY
                m.submitted_at DESC,
                m.report_reference DESC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "observer_id":
                observer_id,

            "status_code":
                status_code,

            "from_date":
                from_date,

            "to_date":
                to_date,

            "limit":
                page_size,

            "offset":
                offset,
        },
    )

    rows = (
        result.mappings().all()
    )

    count_result = await db.execute(
        text(
            f"""
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )
            )

            SELECT COUNT(*)

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            {filter_sql}
            """
        ),
        {
            "observer_id":
                observer_id,

            "status_code":
                status_code,

            "from_date":
                from_date,

            "to_date":
                to_date,
        },
    )

    total = (
        count_result.scalar_one()
    )

    return (
        rows,
        total,
    )


async def get_my_report(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return one Observer-owned report with the richer
    Iteration 2 tracking projection.

    The query begins from reefcare_my_reports(observer_id),
    so another Observer's report is never part of the input
    relation.

    Only Observer-safe data is selected.
    """

    result = await db.execute(
        text(
            """
            WITH mine AS (
                SELECT *

                FROM reefcare_my_reports(
                    CAST(
                        :observer_id
                        AS bigint
                    )
                )

                WHERE
                    report_reference =
                        :report_reference
            )

            SELECT
                m.report_reference,
                m.threat,
                m.area,

                cs.code
                    AS status,

                m.status_label,
                m.closure_label,

                r.observed_at,
                r.estimated_depth_metres,
                r.description,
                r.submitted_at,

                ds.name
                    AS dive_site_name,

                (
                    SELECT COUNT(*)

                    FROM evidence ev

                    WHERE
                        ev.report_id =
                            r.report_id
                ) AS evidence_count,

                COALESCE(
                    latest_event.occurred_at,
                    r.submitted_at
                ) AS last_updated_at,

                CASE
                    WHEN
                        cs.code =
                        'needs_more_info'

                    THEN
                        info_event.note

                    ELSE NULL
                END AS
                    information_request_reason,

                CASE
                    WHEN
                        cs.is_terminal

                    THEN
                        close_event.note

                    ELSE NULL
                END AS
                    public_closure_note

            FROM mine m

            JOIN report r
                ON r.report_reference =
                   m.report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at IS NULL

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
                SELECT
                    e.note

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                    AND e.event_type =
                        'info_requested'

                    AND e.note IS NOT NULL

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) info_event
                ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    e.note

                FROM case_event e

                JOIN case_status terminal_status
                    ON
                        terminal_status
                        .case_status_id =
                        e.to_status_id

                WHERE
                    e.report_id =
                        r.report_id

                    AND
                        terminal_status
                        .is_terminal = TRUE

                    AND e.note IS NOT NULL

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) close_event
                ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    e.occurred_at

                FROM case_event e

                WHERE
                    e.report_id =
                        r.report_id

                ORDER BY
                    e.occurred_at DESC,
                    e.case_event_id DESC

                LIMIT 1
            ) latest_event
                ON TRUE

            LIMIT 1
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    return (
        result.mappings().first()
    )


async def get_report_timeline(
    db: AsyncSession,
    *,
    observer_id: int,
    report_reference: str,
):
    """
    Return deterministic Observer-facing status history.

    reefcare_report_timeline() exposes only:
    - case_status.observer_label
    - occurred_at

    It does not expose:
    - actor identity
    - coordinator identity
    - notes
    - internal event type
    - raw decision data
    """

    result = await db.execute(
        text(
            """
            SELECT
                status_label,
                occurred_at

            FROM reefcare_report_timeline(
                CAST(
                    :report_reference
                    AS text
                ),

                CAST(
                    :observer_id
                    AS bigint
                )
            )
            """
        ),
        {
            "observer_id":
                observer_id,

            "report_reference":
                report_reference,
        },
    )

    return result.mappings().all()