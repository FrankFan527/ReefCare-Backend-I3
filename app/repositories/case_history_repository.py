# ---------------------------------------------------------------------------
# Closed case and referral history (US5.8 / API-10).
#
# No new table is required.
#
# History is projected from:
# - report
# - case_status
# - case_decision
# - closure_reason
# - case_event
#
# Ownership is enforced directly in SQL.
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


REFERRAL_RESPONSE_TYPE: str = (
    "refer_or_share"
)

CLOSED_EVENT_TYPE: str = (
    "closed"
)


async def list_closed_cases(
    db: AsyncSession,
    coordinator_id: int,
    closure_reason_code: (
        str | None
    ),
    threat_code: (
        str | None
    ),
    closed_from: (
        datetime | None
    ),
    closed_to: (
        datetime | None
    ),
    was_referred: (
        bool | None
    ),
    page: int,
    page_size: int,
):
    """
    Return the coordinator's own terminal cases, newest
    closure first.

    case_status.is_terminal is used rather than a hardcoded
    list of closed status codes. This means new I2 terminal
    status closed_resolved is included automatically.

    Referral rows created only as part of closure are not
    counted as historical referrals.
    """

    the_offset = (
        (page - 1)
        * page_size
    )

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                tc.label
                    AS threat,

                tc.code
                    AS threat_code,

                ds.public_area_label
                    AS area,

                cs.code
                    AS status_code,

                cs.internal_label
                    AS status_label,

                r.submitted_at,

                cr.code
                    AS closure_reason_code,

                cr.internal_label
                    AS closure_reason_label,

                cr.observer_label
                    AS closure_observer_label,

                closing.decision_note
                    AS closure_note,

                closing.decided_at
                    AS decided_at,

                COALESCE(
                    closed_event.occurred_at,
                    closing.decided_at
                ) AS closed_at,

                ref.referral_count,

                COUNT(*) OVER ()
                    AS total_count

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

                AND cs.is_terminal
                    IS TRUE

            JOIN threat_category AS tc
                ON tc.threat_category_id =
                   r.threat_category_id

            LEFT JOIN dive_session AS dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site AS ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN LATERAL (
                SELECT
                    cd.closure_reason_id,
                    cd.decision_note,
                    cd.decided_at

                FROM case_decision AS cd

                WHERE
                    cd.report_id =
                        r.report_id

                    AND
                    cd.closure_reason_id
                        IS NOT NULL

                ORDER BY
                    cd.decided_at DESC,
                    cd.case_decision_id DESC

                LIMIT 1
            ) AS closing
                ON TRUE

            LEFT JOIN closure_reason AS cr
                ON cr.closure_reason_id =
                   closing.closure_reason_id

            LEFT JOIN LATERAL (
                SELECT
                    e.occurred_at

                FROM case_event AS e

                WHERE
                    e.report_id =
                        r.report_id

                    AND e.event_type =
                        :closed_event_type

                ORDER BY
                    e.case_event_id DESC

                LIMIT 1
            ) AS closed_event
                ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)
                        AS referral_count

                FROM case_decision AS cd2

                WHERE
                    cd2.report_id =
                        r.report_id

                    AND cd2.response_type =
                        :referral_response_type

                    AND COALESCE(
                        BTRIM(
                            cd2.referred_to
                        ),
                        ''
                    ) <> ''

                    AND
                    cd2.closure_reason_id
                        IS NULL
            ) AS ref
                ON TRUE

            WHERE
                r.claimed_by_user_id =
                    :coordinator_id

                AND r.deleted_at
                    IS NULL

                AND (
                    CAST(
                        :closure_reason_code
                        AS text
                    ) IS NULL

                    OR cr.code =
                        :closure_reason_code
                )

                AND (
                    CAST(
                        :threat_code
                        AS text
                    ) IS NULL

                    OR tc.code =
                        :threat_code
                )

                AND (
                    CAST(
                        :closed_from
                        AS timestamptz
                    ) IS NULL

                    OR COALESCE(
                        closed_event
                        .occurred_at,
                        closing
                        .decided_at
                    ) >= :closed_from
                )

                AND (
                    CAST(
                        :closed_to
                        AS timestamptz
                    ) IS NULL

                    OR COALESCE(
                        closed_event
                        .occurred_at,
                        closing
                        .decided_at
                    ) < :closed_to
                )

                AND (
                    CAST(
                        :was_referred
                        AS boolean
                    ) IS NULL

                    OR (
                        ref.referral_count
                        > 0
                    ) = :was_referred
                )

            ORDER BY
                COALESCE(
                    closed_event.occurred_at,
                    closing.decided_at
                ) DESC NULLS LAST,

                r.report_id DESC

            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "coordinator_id":
                coordinator_id,

            "closure_reason_code":
                closure_reason_code,

            "threat_code":
                threat_code,

            "closed_from":
                closed_from,

            "closed_to":
                closed_to,

            "was_referred":
                was_referred,

            "closed_event_type":
                CLOSED_EVENT_TYPE,

            "referral_response_type":
                REFERRAL_RESPONSE_TYPE,

            "limit":
                page_size,

            "offset":
                the_offset,
        },
    )

    the_rows = (
        the_result
        .mappings()
        .all()
    )

    the_total = (
        the_rows[0][
            "total_count"
        ]
        if the_rows
        else 0
    )

    return (
        the_rows,
        the_total,
    )


async def list_referral_history(
    db: AsyncSession,
    report_references: list[
        str
    ],
    coordinator_id: int,
) -> list[dict]:
    """
    Return genuine referral decisions for the supplied
    coordinator-owned reports.

    Closure-generated case_decision rows are excluded by
    requiring closure_reason_id IS NULL.
    """

    if not report_references:
        return []

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                cd.referred_to,

                cd.decision_note,

                cd.decided_at
                    AS referred_at,

                u.display_name
                    AS decided_by_name

            FROM case_decision AS cd

            JOIN report AS r
                ON r.report_id =
                   cd.report_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   cd.coordinator_id

            WHERE
                r.report_reference =
                    ANY(
                        :report_references
                    )

                AND
                r.claimed_by_user_id =
                    :coordinator_id

                AND r.deleted_at
                    IS NULL

                AND cd.response_type =
                    :referral_response_type

                AND COALESCE(
                    BTRIM(
                        cd.referred_to
                    ),
                    ''
                ) <> ''

                AND
                cd.closure_reason_id
                    IS NULL

            ORDER BY
                cd.decided_at ASC,
                cd.case_decision_id ASC
            """
        ),
        {
            "report_references":
                report_references,

            "coordinator_id":
                coordinator_id,

            "referral_response_type":
                REFERRAL_RESPONSE_TYPE,
        },
    )

    return [
        dict(
            the_row
        )
        for the_row
        in the_result
        .mappings()
        .all()
    ]


async def closure_reason_code_exists(
    db: AsyncSession,
    closure_reason_code: str,
) -> bool:
    """
    Whether a closure reason exists.

    Historical filtering checks existence, not current
    selectability.
    """

    the_result = await db.execute(
        text(
            """
            SELECT 1

            FROM closure_reason

            WHERE
                code =
                    :closure_reason_code
            """
        ),
        {
            "closure_reason_code":
                closure_reason_code,
        },
    )

    return (
        the_result.first()
        is not None
    )


async def threat_code_exists(
    db: AsyncSession,
    threat_code: str,
) -> bool:
    """
    Whether a threat-category code exists.
    """

    the_result = await db.execute(
        text(
            """
            SELECT 1

            FROM threat_category

            WHERE
                code =
                    :threat_code
            """
        ),
        {
            "threat_code":
                threat_code,
        },
    )

    return (
        the_result.first()
        is not None
    )