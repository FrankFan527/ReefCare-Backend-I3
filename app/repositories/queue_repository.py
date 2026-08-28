from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_incoming_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
):
    """
    Read the coordinator queue through v_unclaimed_queue.

    The database view is the authoritative queue-safe source
    and must not expose precise coordinates.
    """

    offset = (page - 1) * page_size

    result = await db.execute(
        text(
            """
            SELECT
                report_reference,
                threat,
                area,
                status,
                submitted_at,
                hours_in_queue

            FROM v_unclaimed_queue

            ORDER BY
                submitted_at ASC,
                report_id ASC

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
            SELECT count(*)
            FROM v_unclaimed_queue
            """
        )
    )

    total = count_result.scalar_one()

    return rows, total