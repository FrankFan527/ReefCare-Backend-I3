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

    Iteration 2 US5.1 AC1 adds an evidence-completeness
    indicator and a priority cue. Neither is stored. This
    query returns the raw signals they are derived from,
    and triage_priority_service turns those into the two
    displayed values.

    Three of the signals are deliberately reduced to counts
    and booleans here rather than returned whole:

      evidence_count       counts the files, and returns
                           no storage key or filename

      has_location_detail  says whether the coordinator
                           could find the site again, but
                           never returns the coordinates,
                           which stay behind the location
                           access rules

      description_length   says whether enough was written
                           to review, without putting the
                           description itself into a queue
                           response
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
        "response_recommended",
    )

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                tc.label AS threat,

                -- the code drives the US5.7 threat rule,
                -- the label is what the coordinator reads
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

                -- US5.1 AC1 evidence-completeness signals
                COALESCE(ev.evidence_count, 0)
                    AS evidence_count,

                -- true when the coordinator has some way to
                -- relocate the threat: either a dropped pin
                -- or written relocation notes. The values
                -- themselves are never selected.
                (
                    rl.report_location_id IS NOT NULL
                    AND (
                        rl.latitude IS NOT NULL
                        OR COALESCE(
                            BTRIM(rl.relocation_notes),
                            ''
                        ) <> ''
                    )
                ) AS has_location_detail,

                LENGTH(BTRIM(r.description))
                    AS description_length,

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

            LEFT JOIN report_location AS rl
                ON rl.report_location_id =
                   r.report_location_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   r.claimed_by_user_id

            -- LATERAL rather than a GROUP BY: the queue
            -- selects a wide row per report, and grouping
            -- would force every column into the GROUP BY
            -- clause for the sake of one count.
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS evidence_count
                FROM evidence AS e
                WHERE e.report_id = r.report_id
            ) AS ev ON TRUE

            WHERE
                r.deleted_at IS NULL

                AND cs.code IN (
                    'received',
                    'claimed',
                    'under_review',
                    'needs_more_info',
                    'evidence_accepted',
                    'monitoring',
                    'referred',
                    'response_recommended'
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
                    'referred',
                    'response_recommended'
                )
            """
        )
    )

    total = count_result.scalar_one()

    return rows, total