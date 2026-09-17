from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_incoming_reports(
    db: AsyncSession,
    coordinator_id: int,
    page: int,
    page_size: int,
):
    """
    Return the active coordinator queue.

    Unclaimed intake reports remain visible to all
    coordinators.

    Once a report is claimed, the active case remains
    visible only to the coordinator who currently owns it.

    Iteration 2 action-stage statuses remain active until
    an explicit terminal closure succeeds:

    - response_recommended
    - response_planned
    - response_complete

    Terminal closed reports are excluded and belong in the
    closed-case history API.

    Only queue-safe fields are selected. Precise
    coordinates and private evidence are never returned
    through this query.

    US5.1 / US5.7 triage values are derived later by
    triage_priority_service.
    """

    offset = (
        page - 1
    ) * page_size

    active_owned_status_codes = (
        "claimed",
        "under_review",
        "needs_more_info",
        "evidence_accepted",
        "monitoring",
        "referred",
        "response_recommended",
        "response_planned",
        "response_complete",
    )

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                tc.label AS threat,
                tc.code AS threat_code,

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

                COALESCE(
                    ev.evidence_count,
                    0
                ) AS evidence_count,

                (
                    rl.report_location_id
                        IS NOT NULL

                    AND (
                        rl.latitude
                            IS NOT NULL

                        OR COALESCE(
                            BTRIM(
                                rl.relocation_notes
                            ),
                            ''
                        ) <> ''
                    )
                ) AS has_location_detail,

                LENGTH(
                    BTRIM(
                        r.description
                    )
                ) AS description_length,

                r.claimed_by_user_id,
                r.claimed_at,

                u.display_name
                    AS owner_display_name

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

            LEFT JOIN report_location AS rl
                ON rl.report_location_id =
                   r.report_location_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   r.claimed_by_user_id

            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)
                        AS evidence_count

                FROM evidence AS e

                WHERE
                    e.report_id =
                        r.report_id
            ) AS ev
                ON TRUE

            WHERE
                r.deleted_at IS NULL

                AND (
                    (
                        cs.code = 'received'

                        AND
                        r.claimed_by_user_id
                            IS NULL
                    )

                    OR

                    (
                        r.claimed_by_user_id =
                            :coordinator_id

                        AND cs.code IN (
                            'claimed',
                            'under_review',
                            'needs_more_info',
                            'evidence_accepted',
                            'monitoring',
                            'referred',
                            'response_recommended',
                            'response_planned',
                            'response_complete'
                        )
                    )
                )

            ORDER BY
                r.submitted_at ASC,
                r.report_id ASC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "coordinator_id":
                coordinator_id,

            "limit":
                page_size,

            "offset":
                offset,
        },
    )

    rows = (
        result
        .mappings()
        .all()
    )

    count_result = await db.execute(
        text(
            """
            SELECT
                COUNT(*)

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

            WHERE
                r.deleted_at IS NULL

                AND (
                    (
                        cs.code = 'received'

                        AND
                        r.claimed_by_user_id
                            IS NULL
                    )

                    OR

                    (
                        r.claimed_by_user_id =
                            :coordinator_id

                        AND cs.code IN (
                            'claimed',
                            'under_review',
                            'needs_more_info',
                            'evidence_accepted',
                            'monitoring',
                            'referred',
                            'response_recommended',
                            'response_planned',
                            'response_complete'
                        )
                    )
                )
            """
        ),
        {
            "coordinator_id":
                coordinator_id,
        },
    )

    total = (
        count_result
        .scalar_one()
    )

    return (
        rows,
        total,
    )