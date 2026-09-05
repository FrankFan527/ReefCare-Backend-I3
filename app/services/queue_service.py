from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.queue_repository import (
    list_incoming_reports as repository_list_incoming_reports,
)
from app.schemas.case import (
    CaseOwnerResponse,
    CoordinatorQueueItem,
    CoordinatorQueueResponse,
)


async def list_incoming_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
) -> CoordinatorQueueResponse:
    """
    Coordinate repository pagination and build the
    coordinator-safe queue response.
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
    """
    Build queue items without exposing sensitive
    report information.

    Claimed reports include their current owner and claim
    time. Unclaimed reports return null for both fields.
    """

    items = []

    for row in rows:
        owner = None

        if row["claimed_by_user_id"] is not None:
            owner = CaseOwnerResponse(
                id=row["claimed_by_user_id"],
                display_name=(
                    row["owner_display_name"]
                ),
            )

        items.append(
            CoordinatorQueueItem(
                report_reference=row[
                    "report_reference"
                ],
                threat=row["threat"],
                area=row["area"],
                status_code=row[
                    "status_code"
                ],
                status_label=row[
                    "status_label"
                ],
                submitted_at=row[
                    "submitted_at"
                ],
                hours_in_queue=row[
                    "hours_in_queue"
                ],
                owner=owner,
                claimed_at=row[
                    "claimed_at"
                ],
            )
        )

    return CoordinatorQueueResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )