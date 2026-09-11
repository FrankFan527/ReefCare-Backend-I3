from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.queue_repository import (
    list_incoming_reports as repository_list_incoming_reports,
)
from app.schemas.case import (
    CaseOwnerResponse,
    CoordinatorQueueItem,
    CoordinatorQueueResponse,
)
from app.services.triage_priority_service import build_triage_cues


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

    US5.1 AC1 and US5.7 add the two triage cues. They are
    computed here rather than stored, because both depend
    on how long the report has been waiting, and a stored
    value would be wrong the moment after it was written.

    KNOWN LIMIT, recorded rather than hidden: because the
    cues are computed after the repository has paginated,
    the queue cannot be sorted by priority across pages.
    Each page is ordered oldest-first and carries its own
    priorities. At Iteration 2 volumes this is invisible.
    If the team later wants a priority-ordered queue, the
    rules have to move into SQL, and this note is why.
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

        # the two triage cues, derived from the raw
        # signals the repository returned
        (
            the_evidence_completeness,
            the_priority,
            the_priority_reasons,
        ) = build_triage_cues(
            threat_code=row["threat_code"],
            evidence_count=row["evidence_count"],
            has_location_detail=bool(
                row["has_location_detail"]
            ),
            description_length=row[
                "description_length"
            ],
            hours_in_queue=row["hours_in_queue"],
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
                evidence_completeness=(
                    the_evidence_completeness
                ),
                evidence_count=row[
                    "evidence_count"
                ],
                priority=the_priority,
                priority_reasons=(
                    the_priority_reasons
                ),
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