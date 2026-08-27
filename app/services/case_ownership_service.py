from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
)


async def get_report_reference(
    db: AsyncSession,
    report_id: int,
) -> str:
    result = await db.execute(
        text(
            """
            SELECT report_reference
            FROM report
            WHERE report_id = :report_id
              AND deleted_at IS NULL
            """
        ),
        {
            "report_id": report_id,
        },
    )

    report_reference = result.scalar_one_or_none()

    if report_reference is None:
        raise NotFoundError(
            "Report not found"
        )

    return report_reference


async def claim_report_atomically(
    db: AsyncSession,
    report_id: int,
    coordinator_id: int,
) -> str:
    """
    Claim a report through reefcare_claim_report().

    PostgreSQL is the final authority for:
    - one owner per case
    - active coordinator validation
    - coordinator role validation
    - concurrency protection
    - claim event creation
    """

    report_reference = await get_report_reference(
        db=db,
        report_id=report_id,
    )

    try:
        result = await db.execute(
            text(
                """
                SELECT reefcare_claim_report(
                    :report_reference,
                    :coordinator_id
                )
                """
            ),
            {
                "report_reference": report_reference,
                "coordinator_id": coordinator_id,
            },
        )

        claimed = result.scalar_one()

        if not claimed:
            await db.rollback()

            raise ConflictError(
                "Report has already been claimed"
            )

        await db.commit()

        return report_reference

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
    report_id: int,
):
    result = await db.execute(
        text(
            """
            SELECT
                r.report_id,
                r.report_reference,
                r.claimed_by_user_id,
                r.claimed_at,
                u.display_name,
                cs.code AS status_code,
                cs.internal_label AS status_label
            FROM report r

            LEFT JOIN app_user u
                ON u.user_id = r.claimed_by_user_id

            JOIN case_status cs
                ON cs.case_status_id = r.current_status_id

            WHERE r.report_id = :report_id
              AND r.deleted_at IS NULL
            """
        ),
        {
            "report_id": report_id,
        },
    )

    owner = result.mappings().first()

    if owner is None:
        raise NotFoundError(
            "Report not found"
        )

    return owner