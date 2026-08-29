from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories.case_repository import (
    claim_report as repository_claim_report,
    get_report_owner,
)


async def claim_report(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Claim an unowned report.

    Atomicity belongs to PostgreSQL
    reefcare_claim_report(), not to Python.
    """

    try:
        existing = await get_report_owner(
            db=db,
            report_reference=report_reference,
        )

        if existing is None:
            raise NotFoundError(
                "Report not found"
            )

        claimed = await repository_claim_report(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
        )

        if not claimed:
            await db.rollback()

            raise ConflictError(
                "Report has already been claimed"
            )

        await db.commit()

        owner = await get_report_owner(
            db=db,
            report_reference=report_reference,
        )

        return owner

    except (
        ConflictError,
        NotFoundError,
    ):
        raise

    except Exception as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to claim report"
        ) from exc


async def get_current_case_owner(
    db: AsyncSession,
    report_reference: str,
):
    owner = await get_report_owner(
        db=db,
        report_reference=report_reference,
    )

    if owner is None:
        raise NotFoundError(
            "Report not found"
        )

    return owner