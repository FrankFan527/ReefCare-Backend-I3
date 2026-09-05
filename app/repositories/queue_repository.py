from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_incoming_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
):
    """
    Return the active coordinator queue.

    Iteration 1 US5.1 requires submitted reports to remain
    visible with their current status.

    The queue includes active reports from initial receipt
    through coordinator review/routing, while terminal
    closed reports are excluded.

    Only queue-safe fields are selected. Precise
    coordinates and private evidence are never returned
    through this query.
    """

    offset = (page - 1) * page_size

    active_status_codes = (
        "received",
        "claimed",
        "under_review",
        "needs_more_info",
        "evidence_accepted",
        "monitoring",
        "referred",
    )

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                tc.label AS threat,

                ds.public_area_label AS area,

                cs.code AS status_code,
                cs.internal_label AS status_label,

                r.submitted_at,

                CAST(
                    FLOOR(
                        EXTRACT(
                            EPOCH FROM (
                                CURRENT_TIMESTAMP
                                - r.submitted_at
                            )
                        ) / 3600
                    )
                    AS INTEGER
                ) AS hours_in_queue,

                r.claimed_by_user_id,
                r.claimed_at,

                u.display_name AS owner_display_name

            FROM report AS r

            JOIN threat_category AS tc
                ON tc.threat_category_id =
                   r.threat_category_id

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session AS dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site AS ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   r.claimed_by_user_id

            WHERE
                r.deleted_at IS NULL

                AND cs.code IN (
                    'received',
                    'claimed',
                    'under_review',
                    'needs_more_info',
                    'evidence_accepted',
                    'monitoring',
                    'referred'
                )

            ORDER BY
                r.submitted_at ASC,
                r.report_id ASC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "limit": page_size,
            "offset": offset,
        },
    )

    rows = result.mappings().all()

    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

            WHERE
                r.deleted_at IS NULL

                AND cs.code IN (
                    'received',
                    'claimed',
                    'under_review',
                    'needs_more_info',
                    'evidence_accepted',
                    'monitoring',
                    'referred'
                )
            """
        )
    )

    total = count_result.scalar_one()

    return rows, total