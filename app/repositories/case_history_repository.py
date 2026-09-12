# ---------------------------------------------------------------------------
# Closed case and referral history (US5.8).
#
# No new table. Section 8.1 of the Iteration 2 backend document is explicit:
# "Prefer query over existing report/case_event/case_decision. Do not duplicate
# case history unnecessarily." Everything below is a read.
#
# Four facts about the schema shape this file:
#
#   report carries no closure columns at all. A case is closed because its
#   current_status_id points at a case_status row with is_terminal = true.
#
#   The closure reason lives on case_decision, not on the report, and a report
#   may have several decision rows if it went back for more information and was
#   reviewed again. The closing decision is the most recent one carrying a
#   closure_reason_id.
#
#   Referrals are plural for the same reason. US5.8 AC3 asks for referral
#   history, so every referral round is returned rather than only the last.
#
#   reefcare_close_report() writes its own case_decision row and derives
#   response_type from the closure reason, so closing as referred_other_org
#   produces a row indistinguishable from a real referral. Both referral
#   queries below exclude rows carrying a closure_reason_id for that reason.
# ---------------------------------------------------------------------------

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


REFERRAL_RESPONSE_TYPE: str = "refer_or_share"
CLOSED_EVENT_TYPE: str = "closed"


async def list_closed_cases(
    db: AsyncSession,
    coordinator_id: int,
    closure_reason_code: str | None,
    threat_code: str | None,
    closed_from: datetime | None,
    closed_to: datetime | None,
    was_referred: bool | None,
    page: int,
    page_size: int,
):
    """
    Return the coordinator's own closed cases, newest closure first.

    Scoped to r.claimed_by_user_id = :coordinator_id in the query itself rather
    than filtered afterwards. US5.8 AC1 says "the Coordinator's authorised
    closed-case history", and a WHERE clause is a stronger guarantee of that
    than a service-layer check over a wider result set.

    Every filter is written as (:param IS NULL OR <condition>), so one query
    serves all combinations and an absent filter cannot accidentally exclude
    rows.

    COUNT(*) OVER () returns the total before LIMIT, which avoids repeating
    this WHERE clause in a separate count query. With five optional filters, a
    duplicated predicate is a real risk: the two copies drift, and the symptom
    is a pagination total that disagrees with the page.

    closed_at falls back from the 'closed' case_event to the closing decision's
    timestamp. The event is the better source because it records when the
    status actually moved, but a case closed before that event type was in use
    would otherwise sort as though it had no closure date at all.
    """

    the_offset = (page - 1) * page_size

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,

                tc.label AS threat,
                tc.code  AS threat_code,

                ds.public_area_label AS area,

                cs.code           AS status_code,
                cs.internal_label AS status_label,

                r.submitted_at,

                cr.code           AS closure_reason_code,
                cr.internal_label AS closure_reason_label,
                cr.observer_label AS closure_observer_label,

                closing.decision_note AS closure_note,
                closing.decided_at    AS decided_at,

                COALESCE(
                    closed_event.occurred_at,
                    closing.decided_at
                ) AS closed_at,

                ref.referral_count,

                COUNT(*) OVER () AS total_count

            FROM report AS r

            -- is_terminal is what makes a case closed. Listing the four
            -- closed_* codes here instead would silently miss
            -- closed_resolved, added for US7.1.
            JOIN case_status AS cs
                ON cs.case_status_id = r.current_status_id
               AND cs.is_terminal IS TRUE

            JOIN threat_category AS tc
                ON tc.threat_category_id = r.threat_category_id

            LEFT JOIN dive_session AS dsn
                ON dsn.dive_session_id = r.dive_session_id

            LEFT JOIN dive_site AS ds
                ON ds.dive_site_id = dsn.dive_site_id

            -- The decision that actually closed the case: the most recent one
            -- carrying a closure reason.
            LEFT JOIN LATERAL (
                SELECT
                    cd.closure_reason_id,
                    cd.decision_note,
                    cd.decided_at
                FROM case_decision AS cd
                WHERE
                    cd.report_id = r.report_id
                    AND cd.closure_reason_id IS NOT NULL
                ORDER BY cd.decided_at DESC, cd.case_decision_id DESC
                LIMIT 1
            ) AS closing ON TRUE

            LEFT JOIN closure_reason AS cr
                ON cr.closure_reason_id = closing.closure_reason_id

            LEFT JOIN LATERAL (
                SELECT e.occurred_at
                FROM case_event AS e
                WHERE
                    e.report_id = r.report_id
                    AND e.event_type = :closed_event_type
                ORDER BY e.case_event_id DESC
                LIMIT 1
            ) AS closed_event ON TRUE

            -- Counted rather than fetched here. The referral detail is
            -- returned by list_referral_history() in one query for the whole
            -- page, instead of one query per row.
            --
            -- closure_reason_id IS NULL matches the same exclusion in
            -- list_referral_history(). Both must agree, or was_referred=true
            -- returns a case whose referrals array then comes back empty.
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS referral_count
                FROM case_decision AS cd2
                WHERE
                    cd2.report_id = r.report_id
                    AND cd2.response_type = :referral_response_type
                    AND COALESCE(BTRIM(cd2.referred_to), '') <> ''
                    AND cd2.closure_reason_id IS NULL
            ) AS ref ON TRUE

            WHERE
                r.claimed_by_user_id = :coordinator_id
                AND r.deleted_at IS NULL

                AND (
                    CAST(:closure_reason_code AS text) IS NULL
                    OR cr.code = :closure_reason_code
                )

                AND (
                    CAST(:threat_code AS text) IS NULL
                    OR tc.code = :threat_code
                )

                AND (
                    CAST(:closed_from AS timestamptz) IS NULL
                    OR COALESCE(
                        closed_event.occurred_at,
                        closing.decided_at
                    ) >= :closed_from
                )

                AND (
                    CAST(:closed_to AS timestamptz) IS NULL
                    OR COALESCE(
                        closed_event.occurred_at,
                        closing.decided_at
                    ) < :closed_to
                )

                AND (
                    CAST(:was_referred AS boolean) IS NULL
                    OR (ref.referral_count > 0) = :was_referred
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
            "coordinator_id": coordinator_id,
            "closure_reason_code": closure_reason_code,
            "threat_code": threat_code,
            "closed_from": closed_from,
            "closed_to": closed_to,
            "was_referred": was_referred,
            "closed_event_type": CLOSED_EVENT_TYPE,
            "referral_response_type": REFERRAL_RESPONSE_TYPE,
            "limit": page_size,
            "offset": the_offset,
        },
    )

    the_rows = the_result.mappings().all()

    # COUNT(*) OVER () is absent when the result set is empty, which is the one
    # case the window function cannot answer for itself.
    the_total = (
        the_rows[0]["total_count"]
        if the_rows
        else 0
    )

    return the_rows, the_total


async def list_referral_history(
    db: AsyncSession,
    report_references: list[str],
    coordinator_id: int,
) -> list[dict]:
    """
    Return every recorded referral for the given reports, oldest first.

    One query for the whole page rather than one per case. The caller groups
    the rows by report_reference.

    The coordinator filter is repeated here even though the caller has already
    scoped the page. This function takes a list of references that arrives as
    data, and a read that enforces its own authorisation cannot be turned into
    a leak by a future caller passing a reference it should not have.

    Ordered oldest first: US5.8 AC3 asks for referral history, and a history
    reads forwards.
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
                cd.decided_at,

                u.display_name AS decided_by_name

            FROM case_decision AS cd

            JOIN report AS r
                ON r.report_id = cd.report_id

            LEFT JOIN app_user AS u
                ON u.user_id = cd.coordinator_id

            WHERE
                r.report_reference = ANY(:report_references)
                AND r.claimed_by_user_id = :coordinator_id
                AND r.deleted_at IS NULL
                AND cd.response_type = :referral_response_type
                AND COALESCE(BTRIM(cd.referred_to), '') <> ''

                -- A referral is something the coordinator decided, not
                -- something a closure implied. reefcare_close_report() writes
                -- a second case_decision row and derives its response_type
                -- from the closure reason, so closing as referred_other_org
                -- produces a row that looks identical to the original
                -- referral and the same referral appears twice.
                --
                -- That row is required rather than accidental:
                -- trg_report_closure_reason is deferrable and will not let a
                -- case reach a terminal status without a decision carrying a
                -- closure reason. So it is excluded on read instead of
                -- prevented on write.
                --
                -- Filtered on closure_reason_id rather than deduplicated by
                -- organisation, because two genuine referrals to the same body
                -- are a real case: referred, returned, referred again.
                AND cd.closure_reason_id IS NULL

            ORDER BY cd.decided_at ASC, cd.case_decision_id ASC
            """
        ),
        {
            "report_references": report_references,
            "coordinator_id": coordinator_id,
            "referral_response_type": REFERRAL_RESPONSE_TYPE,
        },
    )

    return [
        dict(the_row)
        for the_row in the_result.mappings().all()
    ]


async def closure_reason_code_exists(
    db: AsyncSession,
    closure_reason_code: str,
) -> bool:
    """
    Whether a closure reason code is in the reference table.

    Existence rather than selectability. A coordinator filtering their history
    may legitimately search for a reason that is no longer offered: cases
    closed under it still exist and are still theirs to look at.
    """

    the_result = await db.execute(
        text(
            """
            SELECT 1
            FROM closure_reason
            WHERE code = :closure_reason_code
            """
        ),
        {
            "closure_reason_code": closure_reason_code,
        },
    )

    return the_result.first() is not None


async def threat_code_exists(
    db: AsyncSession,
    threat_code: str,
) -> bool:
    """
    Whether a threat category code is in the reference table.
    """

    the_result = await db.execute(
        text(
            """
            SELECT 1
            FROM threat_category
            WHERE code = :threat_code
            """
        ),
        {
            "threat_code": threat_code,
        },
    )

    return the_result.first() is not None