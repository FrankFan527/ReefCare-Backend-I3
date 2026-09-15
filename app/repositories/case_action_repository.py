# ---------------------------------------------------------------------------
# Conservation action persistence (US7.1 / API-11).
#
# Repositories own SQL.
#
# Every case_action row is tied to one case_event.
# Action evidence reuses that relationship:
#
# case_action.case_event_id
#          =
# evidence.case_event_id
#
# This makes an uploaded file traceable to the specific
# action without creating a second action-evidence link
# table.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


ACTION_EVENT_TYPE: str = (
    "action_recorded"
)


async def get_action_type(
    db: AsyncSession,
    action_type_code: str,
) -> dict | None:
    """
    Return one action type or None when the code is unknown.
    """

    result = await db.execute(
        text(
            """
            SELECT
                action_type_id,
                code,
                label,
                description,
                is_selectable

            FROM action_type

            WHERE
                code =
                    :action_type_code
            """
        ),
        {
            "action_type_code":
                action_type_code,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(
        row
    )


async def list_selectable_action_types(
    db: AsyncSession,
) -> list[dict]:
    """
    Return action types currently selectable by a
    coordinator.
    """

    result = await db.execute(
        text(
            """
            SELECT
                code,
                label,
                description

            FROM action_type

            WHERE
                is_selectable
                    IS TRUE

            ORDER BY
                display_order,
                code
            """
        )
    )

    return [
        dict(
            row
        )
        for row
        in result
        .mappings()
        .all()
    ]


async def insert_standalone_action_event(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    note: (
        str | None
    ),
) -> int:
    """
    Write an action_recorded event without moving status.

    Used when a case already sits in the target action
    status.
    """

    result = await db.execute(
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
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

            RETURNING
                case_event_id
            """
        ),
        {
            "report_reference":
                report_reference,

            "event_type":
                ACTION_EVENT_TYPE,

            "coordinator_id":
                coordinator_id,

            "note":
                note,
        },
    )

    return (
        result.scalar_one()
    )


async def get_latest_action_event_id(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> int | None:
    """
    Locate the latest action_recorded event created for this
    report by the current coordinator.
    """

    result = await db.execute(
        text(
            """
            SELECT
                MAX(
                    e.case_event_id
                )

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id =
                   e.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

                AND e.event_type =
                    :event_type

                AND e.actor_user_id =
                    :coordinator_id
            """
        ),
        {
            "report_reference":
                report_reference,

            "event_type":
                ACTION_EVENT_TYPE,

            "coordinator_id":
                coordinator_id,
        },
    )

    return (
        result.scalar_one()
    )


async def save_case_action(
    db: AsyncSession,
    report_reference: str,
    case_event_id: int,
    action_type_id: int,
    action_state: str,
    action_date: (
        date | None
    ),
    responsible_team: (
        str | None
    ),
    notes: (
        str | None
    ),
    created_by: int,
) -> dict:
    """
    Insert one append-only case_action row.

    The caller commits.
    """

    result = await db.execute(
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
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

            RETURNING
                case_action_id,
                case_event_id,
                action_state,
                action_date,
                responsible_team,
                notes,
                created_by,
                created_at
            """
        ),
        {
            "report_reference":
                report_reference,

            "case_event_id":
                case_event_id,

            "action_type_id":
                action_type_id,

            "action_state":
                action_state,

            "action_date":
                action_date,

            "responsible_team":
                responsible_team,

            "notes":
                notes,

            "created_by":
                created_by,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return {}

    return dict(
        row
    )


async def list_case_actions(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return every action recorded against one report,
    oldest first.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ca.case_action_id,
                ca.case_event_id,

                r.report_reference,

                at.code
                    AS action_type_code,

                at.label
                    AS action_type_label,

                ca.action_state,
                ca.action_date,
                ca.responsible_team,
                ca.notes,

                cs.code
                    AS status_code,

                ca.created_by,

                u.display_name
                    AS created_by_name,

                ca.created_at

            FROM case_action AS ca

            JOIN report AS r
                ON r.report_id =
                   ca.report_id

            JOIN action_type AS at
                ON at.action_type_id =
                   ca.action_type_id

            JOIN case_status AS cs
                ON cs.case_status_id =
                   r.current_status_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                   ca.created_by

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

            ORDER BY
                ca.case_action_id ASC
            """
        ),
        {
            "report_reference":
                report_reference,
        },
    )

    return [
        dict(
            row
        )
        for row
        in result
        .mappings()
        .all()
    ]


async def get_case_action_for_report(
    db: AsyncSession,
    report_reference: str,
    action_id: int,
) -> dict | None:
    """
    Return an action only when it belongs to the requested
    live report.

    This prevents action IDs being attached across cases.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ca.case_action_id,
                ca.case_event_id,
                ca.report_id

            FROM case_action AS ca

            JOIN report AS r
                ON r.report_id =
                   ca.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND ca.case_action_id =
                    :action_id

                AND r.deleted_at
                    IS NULL

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "action_id":
                action_id,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(
        row
    )


async def save_action_evidence(
    db: AsyncSession,
    report_reference: str,
    case_event_id: int,
    uploaded_by_user_id: int,
    file_reference: str,
    file_size_bytes: int,
) -> dict | None:
    """
    Insert private evidence metadata attached to an action's
    case event.

    file_reference remains internal and is never returned
    by the API response schema.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO evidence
                (
                    report_id,
                    dive_session_id,
                    media_type,
                    file_reference,
                    file_size_bytes,
                    display_order,
                    case_event_id,
                    uploaded_by_user_id
                )

            SELECT
                r.report_id,
                r.dive_session_id,
                'photo',
                :file_reference,
                :file_size_bytes,

                COALESCE(
                    (
                        SELECT
                            MAX(
                                e2.display_order
                            ) + 1

                        FROM evidence AS e2

                        WHERE
                            e2.report_id =
                                r.report_id
                    ),
                    0
                ),

                :case_event_id,
                :uploaded_by_user_id

            FROM report AS r

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

            RETURNING
                evidence_id,
                media_type,
                file_size_bytes,
                uploaded_at
            """
        ),
        {
            "report_reference":
                report_reference,

            "file_reference":
                file_reference,

            "file_size_bytes":
                file_size_bytes,

            "case_event_id":
                case_event_id,

            "uploaded_by_user_id":
                uploaded_by_user_id,
        },
    )

    row = (
        result
        .mappings()
        .first()
    )

    if row is None:
        return None

    return dict(
        row
    )


async def list_action_evidence_metadata(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return safe evidence metadata grouped by the action
    sharing the same case_event.
    """

    result = await db.execute(
        text(
            """
            SELECT
                ca.case_action_id,

                e.evidence_id,
                e.media_type,
                e.file_size_bytes,
                e.uploaded_at

            FROM case_action AS ca

            JOIN report AS r
                ON r.report_id =
                   ca.report_id

            JOIN evidence AS e
                ON e.report_id =
                   ca.report_id

                AND e.case_event_id =
                    ca.case_event_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

            ORDER BY
                ca.case_action_id ASC,
                e.display_order ASC,
                e.evidence_id ASC
            """
        ),
        {
            "report_reference":
                report_reference,
        },
    )

    return [
        dict(
            row
        )
        for row
        in result
        .mappings()
        .all()
    ]