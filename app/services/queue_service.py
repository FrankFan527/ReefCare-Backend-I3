from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.queue_repository import (
    list_incoming_reports as repository_list_incoming_reports,
)
from app.schemas.case import (
    CoordinatorQueueItem,
    CoordinatorQueueResponse,
)


async def list_incoming_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
) -> CoordinatorQueueResponse:
    """
    Coordinate repository pagination and API-safe queue
    projection.
    """

    rows, total = (
        await repository_list_incoming_reports(
            db=db,
            page=page,
            page_size=page_size,
        )
    )

    return build_queue_response(
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
    )


def build_queue_response(
    rows,
    page: int,
    page_size: int,
    total: int,
) -> CoordinatorQueueResponse:
    items = [
        CoordinatorQueueItem(
            report_reference=row[
                "report_reference"
            ],
            threat=row["threat"],
            area=row["area"],
            status_label=row["status"],
            submitted_at=row["submitted_at"],
            hours_in_queue=row[
                "hours_in_queue"
            ],
        )
        for row in rows
    ]

    return CoordinatorQueueResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )