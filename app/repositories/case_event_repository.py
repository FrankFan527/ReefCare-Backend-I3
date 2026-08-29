from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_case_events(
    db: AsyncSession,
    report_reference: str,
):
    """
    Read append-only case_event history for an internal,
    authorised case trace.

    This repository performs READS ONLY.

    Workflow functions such as reefcare_claim_report(),
    reefcare_change_status(), and reefcare_close_report()
    already create their required case_event rows.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ce.case_event_id,
                ce.event_type,

                from_status.code
                    AS from_status_code,

                to_status.code
                    AS to_status_code,

                ce.actor_user_id,

                actor.display_name
                    AS actor_display_name,

                ce.note,
                ce.occurred_at

            FROM case_event ce

            JOIN report r
                ON r.report_id = ce.report_id

            LEFT JOIN case_status from_status
                ON from_status.case_status_id =
                   ce.from_status_id

            LEFT JOIN case_status to_status
                ON to_status.case_status_id =
                   ce.to_status_id

            LEFT JOIN app_user actor
                ON actor.user_id =
                   ce.actor_user_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

            ORDER BY
                ce.occurred_at ASC,
                ce.case_event_id ASC
            """
        ),
        {
            "report_reference": report_reference,
        },
    )

    return result.mappings().all()