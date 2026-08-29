from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.case_event_repository import (
    list_case_events,
)
from app.schemas.audit import (
    CaseEventResponse,
)


def build_case_event_projection(
    rows,
) -> list[CaseEventResponse]:
    """
    Build the internal safe trace projection.

    Do not expose this directly to observers.
    """

    return [
        CaseEventResponse(
            event_type=row["event_type"],
            from_status_code=row[
                "from_status_code"
            ],
            to_status_code=row[
                "to_status_code"
            ],
            actor_user_id=row[
                "actor_user_id"
            ],
            actor_display_name=row[
                "actor_display_name"
            ],
            note=row["note"],
            occurred_at=row["occurred_at"],
        )
        for row in rows
    ]


async def get_case_trace(
    db: AsyncSession,
    report_reference: str,
) -> list[CaseEventResponse]:
    """
    Read existing PostgreSQL case_event history.

    This service never creates duplicate workflow events.
    """

    rows = await list_case_events(
        db=db,
        report_reference=report_reference,
    )

    return build_case_event_projection(
        rows
    )