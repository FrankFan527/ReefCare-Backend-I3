from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import (
    AuthorizationError,
    DatabaseOperationError,
    NotFoundError,
)


async def get_owned_case(
    db: AsyncSession,
    report_id: int,
    coordinator_id: int,
):
    """
    Load a report only when the authenticated coordinator
    currently owns it.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_id,
                r.report_reference,
                r.observer_id,

                tc.label AS threat,

                r.description,
                r.estimated_depth_metres,

                ds.public_area_label AS area,

                cs.code AS status_code,
                cs.internal_label AS status_label,

                r.submitted_at,

                r.claimed_by_user_id,
                r.claimed_at,

                u.display_name AS claimed_by

            FROM report r

            JOIN threat_category tc
                ON tc.threat_category_id =
                   r.threat_category_id

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN dive_session dsn
                ON dsn.dive_session_id =
                   r.dive_session_id

            LEFT JOIN dive_site ds
                ON ds.dive_site_id =
                   dsn.dive_site_id

            LEFT JOIN app_user u
                ON u.user_id =
                   r.claimed_by_user_id

            WHERE r.report_id = :report_id
              AND r.deleted_at IS NULL
            """
        ),
        {
            "report_id": report_id,
        },
    )

    case = result.mappings().first()

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


async def get_authorised_case_location(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Retrieve precise location through the database-owned
    authorisation function.

    An unauthorised caller receives zero rows by design.
    """

    result = await db.execute(
        text(
            """
            SELECT *
            FROM reefcare_report_location(
                :report_reference,
                :user_id
            )
            """
        ),
        {
            "report_reference": report_reference,
            "user_id": coordinator_id,
        },
    )

    return result.mappings().first()


async def get_case_evidence_metadata(
    db: AsyncSession,
    report_id: int,
):
    """
    Return safe evidence metadata.

    file_reference is deliberately NOT returned here.
    Actual private file access belongs to the evidence
    storage/access layer.
    """

    result = await db.execute(
        text(
            """
            SELECT
                evidence_id,
                media_type,
                captured_at,
                uploaded_at
            FROM evidence
            WHERE report_id = :report_id
            ORDER BY display_order, evidence_id
            """
        ),
        {
            "report_id": report_id,
        },
    )

    return result.mappings().all()


async def set_case_under_review(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    note: str | None = None,
) -> str:
    """
    Move CLAIMED -> UNDER_REVIEW using the only
    database-sanctioned status-change function.
    """

    try:
        result = await db.execute(
            text(
                """
                SELECT reefcare_change_status(
                    :report_reference,
                    :status_code,
                    :actor_user_id,
                    :note,
                    :event_type
                )
                """
            ),
            {
                "report_reference": report_reference,
                "status_code": (
                    CaseStatus.UNDER_REVIEW.value
                ),
                "actor_user_id": coordinator_id,
                "note": note,
                "event_type": "status_change",
            },
        )

        new_status = result.scalar_one()

        await db.commit()

        return new_status

    except Exception as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to move case under review"
        ) from exc



   