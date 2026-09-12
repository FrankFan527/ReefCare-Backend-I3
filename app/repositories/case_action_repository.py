# ---------------------------------------------------------------------------
# Conservation action persistence (US7.1).
#
# Repositories own SQL; services own workflow.
#
# case_action.case_event_id is NOT NULL, so every action must be bound to a
# case history entry in the same transaction that creates it. That is what
# makes US7.1 AC3 structural rather than a convention the service layer has to
# remember. Two functions below produce that event id, because an action does
# not always move the case:
#
#   get_latest_action_event_id()     the action advanced the case, so the event
#                                    was written by reefcare_change_status()
#   insert_standalone_action_event() the case was already in the target status,
#                                    so a plain append-only case_event is
#                                    written with no status change
#
# The second path leaves to_status_id NULL on purpose. reefcare_report_timeline
# filters on to_status_id IS NOT NULL, so a second planned action of a
# different type is recorded for the coordinator without repeating "A response
# has been planned" in the observer's timeline.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# case_event.event_type permits this value from Iteration 2 onwards.
ACTION_EVENT_TYPE: str = "action_recorded"


async def get_action_type(
    db: AsyncSession,
    action_type_code: str,
) -> dict | None:
    """
    Return one action type, or None when the code is unknown.

    is_selectable is read rather than hardcoded so the reference table stays
    the single source of truth, in the same way closure_reason does.
    """

    the_action_type_result = await db.execute(
        text(
            """
            SELECT
                action_type_id,
                code,
                label,
                description,
                is_selectable

            FROM action_type

            WHERE code = :action_type_code
            """
        ),
        {
            "action_type_code": action_type_code,
        },
    )

    the_action_type_row = (
        the_action_type_result
        .mappings()
        .first()
    )

    if the_action_type_row is None:
        return None

    return dict(the_action_type_row)


async def list_selectable_action_types(
    db: AsyncSession,
) -> list[dict]:
    """
    Return the action types a coordinator may currently choose.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                code,
                label,
                description

            FROM action_type

            WHERE is_selectable IS TRUE

            ORDER BY display_order, code
            """
        )
    )

    return [
        dict(the_row)
        for the_row in the_result.mappings().all()
    ]


async def insert_standalone_action_event(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    note: str | None,
) -> int:
    """
    Write an action_recorded event that does not move the case status.

    Used when the case already sits in the status the action implies, for
    example a second planned action on a case that is already
    response_planned.

    from_status_id and to_status_id are both left NULL. The event still
    satisfies US1.4 traceability and US7.1 AC3, but it does not appear in the
    observer timeline, which only returns events carrying a to_status_id.

    The caller commits.
    """

    the_event_result = await db.execute(
        text(
            """
            INSERT INTO case_event
                (
                    report_id,
                    event_type,
                    actor_user_id,
                    note
                )
            SELECT
                r.report_id,
                :event_type,
                :coordinator_id,
                :note

            FROM report AS r

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL

            RETURNING case_event_id
            """
        ),
        {
            "report_reference": report_reference,
            "event_type": ACTION_EVENT_TYPE,
            "coordinator_id": coordinator_id,
            "note": note,
        },
    )

    return the_event_result.scalar_one()


async def get_latest_action_event_id(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> int:
    """
    Find the action_recorded event this transaction just created through
    reefcare_change_status().

    That function returns the status code, not the event id, so the event has
    to be located afterwards. Filtering on the acting coordinator makes it
    safe: a report has exactly one owner at a time, and only the owner may
    record an action, so the highest matching event id belongs to this
    transaction.

    The caller commits.
    """

    the_event_result = await db.execute(
        text(
            """
            SELECT MAX(e.case_event_id)

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id = e.report_id

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL
                AND e.event_type = :event_type
                AND e.actor_user_id = :coordinator_id
            """
        ),
        {
            "report_reference": report_reference,
            "event_type": ACTION_EVENT_TYPE,
            "coordinator_id": coordinator_id,
        },
    )

    return the_event_result.scalar_one()


async def save_case_action(
    db: AsyncSession,
    report_reference: str,
    case_event_id: int,
    action_type_id: int,
    action_state: str,
    action_date: date | None,
    responsible_team: str | None,
    notes: str | None,
    created_by: int,
) -> dict:
    """
    Insert one action record.

    case_action is append-only by grant: reefcare_app holds SELECT and INSERT
    and nothing else. Superseding an action means inserting a later row, never
    updating an earlier one, for the same reason case_event works that way.

    The caller commits.
    """

    the_action_result = await db.execute(
        text(
            """
            INSERT INTO case_action
                (
                    report_id,
                    case_event_id,
                    action_type_id,
                    action_state,
                    action_date,
                    responsible_team,
                    notes,
                    created_by
                )
            SELECT
                r.report_id,
                :case_event_id,
                :action_type_id,
                :action_state,
                :action_date,
                :responsible_team,
                :notes,
                :created_by

            FROM report AS r

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL

            RETURNING
                case_action_id,
                action_state,
                action_date,
                responsible_team,
                notes,
                created_by,
                created_at
            """
        ),
        {
            "report_reference": report_reference,
            "case_event_id": case_event_id,
            "action_type_id": action_type_id,
            "action_state": action_state,
            "action_date": action_date,
            "responsible_team": responsible_team,
            "notes": notes,
            "created_by": created_by,
        },
    )

    the_action_row = (
        the_action_result
        .mappings()
        .first()
    )

    if the_action_row is None:
        return {}

    return dict(the_action_row)


async def list_case_actions(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return every action recorded against one case, oldest first.

    Ordered by case_action_id rather than created_at so two actions written in
    the same transaction still read back in insertion order, matching how
    reefcare_report_timeline() orders.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                ca.case_action_id,

                r.report_reference,

                at.code  AS action_type_code,
                at.label AS action_type_label,

                ca.action_state,
                ca.action_date,
                ca.responsible_team,
                ca.notes,

                cs.code AS status_code,

                ca.created_by,
                u.display_name AS created_by_name,
                ca.created_at

            FROM case_action AS ca

            JOIN report AS r
                ON r.report_id = ca.report_id

            JOIN action_type AS at
                ON at.action_type_id = ca.action_type_id

            JOIN case_status AS cs
                ON cs.case_status_id = r.current_status_id

            LEFT JOIN app_user AS u
                ON u.user_id = ca.created_by

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL

            ORDER BY ca.case_action_id ASC
            """
        ),
        {
            "report_reference": report_reference,
        },
    )

    return [
        dict(the_row)
        for the_row in the_result.mappings().all()
    ]