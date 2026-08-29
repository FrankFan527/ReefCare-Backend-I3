from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import (
    AuthorizationError,
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories.case_repository import (
    change_status,
    get_case,
)
from app.repositories.evidence_repository import (
    list_case_evidence_metadata,
)
from app.repositories.location_repository import (
    get_report_location,
)
from app.services.projection_service import (
    build_coordinator_case_projection,
)


async def get_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Load a case and enforce current coordinator ownership
    before it can be used by a sensitive workflow.
    """

    case = await get_case(
        db=db,
        report_reference=report_reference,
    )

    if case is None:
        raise NotFoundError(
            "Report not found"
        )

    if (
        case["claimed_by_user_id"]
        != coordinator_id
    ):
        raise AuthorizationError(
            "You do not own this case"
        )

    return case


async def get_coordinator_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Build the complete authorised coordinator review
    projection.
    """

    case = await get_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    location = await get_report_location(
        db=db,
        report_reference=report_reference,
        user_id=coordinator_id,
    )

    evidence_rows = (
        await list_case_evidence_metadata(
            db=db,
            report_reference=report_reference,
        )
    )

    return build_coordinator_case_projection(
        case=case,
        location=location,
        evidence_rows=evidence_rows,
    )


async def set_case_under_review(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    note: str | None = None,
):
    """
    Request CLAIMED -> UNDER_REVIEW.

    PostgreSQL case_status_transition remains authoritative.
    """

    await get_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    try:
        new_status = await change_status(
            db=db,
            report_reference=report_reference,
            status_code=(
                CaseStatus.UNDER_REVIEW.value
            ),
            actor_user_id=coordinator_id,
            note=note,
        )

        await db.commit()

        return new_status

    except Exception as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to move case under review"
        ) from exc