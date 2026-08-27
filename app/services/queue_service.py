from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.case import (
    CoordinatorQueueItem,
    CoordinatorQueueResponse,
)


async def list_incoming_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
) -> tuple[list, int]:
    """
    Read the coordinator queue from v_unclaimed_queue.

    The database view already guarantees:
    - only unclaimed reports
    - withdrawn reports excluded
    - no precise coordinates
    - generalised location only
    """

    offset = (page - 1) * page_size

    rows_result = await db.execute(
        text(
            """
            SELECT
                report_id,
                report_reference,
                threat,
                area,
                status,
                submitted_at,
                hours_in_queue
            FROM v_unclaimed_queue
            ORDER BY submitted_at ASC, report_id ASC
            LIMIT :limit
            OFFSET :offset
            """
        ),
        {
            "limit": page_size,
            "offset": offset,
        },
    )

    rows = rows_result.mappings().all()

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


def build_queue_response(
    rows: list,
    page: int,
    page_size: int,
    total: int,
) -> CoordinatorQueueResponse:
    items = [
        CoordinatorQueueItem(
            report_id=row["report_id"],
            report_reference=row["report_reference"],
            threat=row["threat"],
            area=row["area"],
            status_label=row["status"],
            submitted_at=row["submitted_at"],
            hours_in_queue=row["hours_in_queue"],
        )
        for row in rows
    ]

    return CoordinatorQueueResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )