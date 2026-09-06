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

    observed_at is the actual observation timestamp and
    must remain distinct from submitted_at.

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
                r.observed_at,
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
    event_type: str = "status_change",
):
    """
    Request a normal workflow transition through the
    sanctioned PostgreSQL function.

    PostgreSQL remains authoritative for transition validity
    and case_event creation.

    event_type defaults to "status_change" so existing callers are
    unaffected. The information-request endpoint passes "info_requested"
    so the move shows in the observer timeline as a request for more
    information rather than a generic status change.
    """

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
            "status_code": status_code,
            "actor_user_id": actor_user_id,
            "note": note,
            "event_type": event_type,
        },
    )

    return result.scalar_one()


# ---------------------------------------------------------------------------
# Closure support (US5.5).
#
# Ownership for the information-request and decision endpoints is checked in
# case_workflow_service via get_report_owner above; reefcare_change_status()
# does not check it. reefcare_close_report() does check ownership itself.
# ---------------------------------------------------------------------------


async def transition_is_permitted(
    db: AsyncSession,
    from_status_code: str,
    to_status_code: str,
) -> bool:
    """
    Whether case_status_transition allows this move.

    An application pre-check only. PostgreSQL rejects an unlisted transition
    regardless, but asking first lets the route return a 409 naming both
    states instead of surfacing a raw exception.

    Reading the table rather than hardcoding a list means this stays correct
    if the permitted transitions change.
    """

    the_transition_result = await db.execute(
        text(
            """
            SELECT 1
            FROM case_status_transition AS t
            JOIN case_status AS f
                ON f.case_status_id = t.from_status_id
            JOIN case_status AS s
                ON s.case_status_id = t.to_status_id
            WHERE f.code = :from_status_code
              AND s.code = :to_status_code
            """
        ),
        {
            "from_status_code": from_status_code,
            "to_status_code": to_status_code,
        },
    )

    return (
        the_transition_result.first()
        is not None
    )


async def get_closure_reason(
    db: AsyncSession,
    closure_reason_code: str,
) -> dict | None:
    """
    Return a closure reason's rules, or None if the code is unknown.

    requires_note and iteration_added are read rather than hardcoded, so the
    reference data stays the single source of truth.
    """

    the_reason_result = await db.execute(
        text(
            """
            SELECT
                code,
                internal_label,
                observer_label,
                requires_note,
                iteration_added
            FROM closure_reason
            WHERE code =
                :closure_reason_code
            """
        ),
        {
            "closure_reason_code":
                closure_reason_code
        },
    )

    the_reason_row = (
        the_reason_result
        .mappings()
        .first()
    )

    if the_reason_row is None:
        return None

    return dict(the_reason_row)


async def close_report(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    closure_reason_code: str,
    terminal_status_code: str,
    note: str | None = None,
    referred_to: str | None = None,
) -> str:
    """
    Close a case through the only sanctioned path.

    reefcare_close_report() writes the case_decision row and
    terminal status together and enforces coordinator
    ownership.
    """

    the_closure_result = await db.execute(
        text(
            """
            SELECT reefcare_close_report(
                :report_reference,
                :coordinator_id,
                :closure_reason_code,
                :terminal_status_code,
                :note,
                :referred_to
            ) AS terminal_status_code
            """
        ),
        {
            "report_reference":
                report_reference,
            "coordinator_id":
                coordinator_id,
            "closure_reason_code":
                closure_reason_code,
            "terminal_status_code":
                terminal_status_code,
            "note":
                note,
            "referred_to":
                referred_to,
        },
    )

    return (
        the_closure_result.scalar_one()
    )