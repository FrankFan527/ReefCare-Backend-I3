from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def claim_report(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> bool:
    """
    Call the PostgreSQL-owned atomic claim operation.

    reefcare_claim_report() is responsible for:
    - concurrency safety
    - one active owner per report
    - coordinator eligibility
    - claim status
    - claim case_event
    """

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

    return result.scalar_one()


async def get_report_owner(
    db: AsyncSession,
    report_reference: str,
):
    """
    Return current ownership and status information.
    """

    result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,
                r.claimed_by_user_id,
                r.claimed_at,

                u.display_name,

                cs.code AS status_code,
                cs.internal_label AS status_label

            FROM report r

            LEFT JOIN app_user u
                ON u.user_id =
                   r.claimed_by_user_id

            JOIN case_status cs
                ON cs.case_status_id =
                   r.current_status_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL
            """
        ),
        {
            "report_reference": report_reference,
        },
    )

    return result.mappings().first()


async def get_case(
    db: AsyncSession,
    report_reference: str,
):
    """
    Return the internal case aggregate required by the
    coordinator service.

    Ownership must be checked by the service before the
    result is exposed externally.
    """

    result = await db.execute(
        text(
            """
            SELECT
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

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL
            """
        ),
        {
            "report_reference": report_reference,
        },
    )

    return result.mappings().first()


async def change_status(
    db: AsyncSession,
    report_reference: str,
    status_code: str,
    actor_user_id: int,
    note: str | None = None,
):
    """
    Request a normal workflow transition through the
    sanctioned PostgreSQL function.

    PostgreSQL remains authoritative for transition validity
    and case_event creation.
    """

    result = await db.execute(
        text(
            """
            SELECT reefcare_change_status(
                :report_reference,
                :status_code,
                :actor_user_id,
                :note
            )
            """
        ),
        {
            "report_reference": report_reference,
            "status_code": status_code,
            "actor_user_id": actor_user_id,
            "note": note,
        },
    )

    return result.scalar_one()