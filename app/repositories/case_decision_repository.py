# ---------------------------------------------------------------------------
# Case decision persistence (US5.4).
#
# Repositories own SQL; services own workflow.
#
# NOTE: unlike closure, there is no sanctioned database function for recording
# a non-terminal decision. reefcare_close_report() writes a case_decision row
# as part of closing, but a decision recorded on its own is a plain INSERT.
# That means no database-level ownership check applies here either, and the
# service layer is again the only thing enforcing it.
#
# trg_case_decision_validate still fires on this INSERT and will reject a
# refer_or_share decision with no referred_to, and any Iteration 2 closure
# reason. Those remain authoritative regardless of what Python checked first.
# ---------------------------------------------------------------------------
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def save_case_decision(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    response_type: str,
    decision_note: str | None = None,
    referred_to: str | None = None,
) -> dict:
    """
    Insert one non-terminal case_decision row.

    closure_reason_id is deliberately left NULL. A decision recorded here is
    not a closure, and reefcare_close_report() writes its own case_decision
    row with the reason attached when the case is actually closed.

    The report is resolved from its reference inside the statement rather than
    in a separate query, so there is no window in which the report could be
    withdrawn between lookup and insert.

    The caller commits.
    """

    the_decision_result = await db.execute(
        text(
            """
            INSERT INTO case_decision
                (report_id, coordinator_id, response_type,
                 decision_note, referred_to)
            SELECT
                r.report_id,
                :coordinator_id,
                :response_type,
                :decision_note,
                :referred_to
            FROM report AS r
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL
            RETURNING case_decision_id, response_type, decided_at, coordinator_id
            """
        ),
        {
            "report_reference": report_reference,
            "coordinator_id": coordinator_id,
            "response_type": response_type,
            "decision_note": decision_note,
            "referred_to": referred_to,
        },
    )

    return dict(the_decision_result.mappings().one())


async def get_latest_decision(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Return the most recent decision on a case, or None if there is none.

    The closure endpoint needs this: US5.5 requires a decision to exist before
    a case can be closed, and that ordering is not enforced anywhere in the
    database.
    """

    the_decision_result = await db.execute(
        text(
            """
            SELECT
                cd.case_decision_id,
                cd.response_type,
                cd.referred_to,
                cd.decision_note,
                cd.decided_at,
                cd.coordinator_id
            FROM case_decision AS cd
            JOIN report AS r
                ON r.report_id = cd.report_id
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL
            ORDER BY cd.decided_at DESC, cd.case_decision_id DESC
            LIMIT 1
            """
        ),
        {"report_reference": report_reference},
    )

    the_decision_row = the_decision_result.mappings().first()

    if the_decision_row is None:
        return None

    return dict(the_decision_row)