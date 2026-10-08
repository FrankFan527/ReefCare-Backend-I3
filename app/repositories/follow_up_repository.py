# ---------------------------------------------------------------------------
# US7.1 / US7.2 follow-up persistence.
#
# Reads and writes the Iteration 3 columns on case_action. The Iteration 2
# case_action_repository keeps its own narrower queries for the /actions
# routes, so neither file has to change when the other does.
#
# case_action carries SELECT and INSERT for the runtime role and nothing else,
# so a correction is an appended row pointing at the record it replaces.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# one projection used by the list and the single-record read, so a field can
# never appear in one and be missing from the other
THE_FOLLOW_UP_SELECT: str = """
    SELECT
        ca.case_action_id,
        ca.case_event_id,
        r.report_reference,

        ca.follow_up_type,
        ca.action_state      AS follow_up_state,
        ca.recording_level,

        at.code              AS action_type_code,
        at.label             AS action_type_label,

        ca.action_date,
        ca.responsible_team,
        ca.source_reference,
        ca.observations,
        ca.recorded_outcome,
        ca.notes,

        mc.code              AS condition_code,
        mc.label             AS condition_label,
        reviewer.display_name AS condition_reviewed_by_name,

        ca.next_follow_up_required,
        ca.next_follow_up_date,

        ca.is_publishable,
        ca.is_demonstration,

        ca.supersedes_case_action_id,
        (
            SELECT later.case_action_id
            FROM case_action AS later
            WHERE later.supersedes_case_action_id = ca.case_action_id
            ORDER BY later.case_action_id DESC
            LIMIT 1
        )                    AS superseded_by_case_action_id,

        cs.code              AS status_code,

        ca.created_by,
        author.display_name  AS created_by_name,
        ca.created_at

    FROM case_action AS ca
    JOIN report AS r            ON r.report_id = ca.report_id
    JOIN case_status AS cs      ON cs.case_status_id = r.current_status_id
    JOIN action_type AS at      ON at.action_type_id = ca.action_type_id
    LEFT JOIN monitoring_condition AS mc
                                ON mc.monitoring_condition_id = ca.monitoring_condition_id
    LEFT JOIN app_user AS author
                                ON author.user_id = ca.created_by
    LEFT JOIN app_user AS reviewer
                                ON reviewer.user_id = ca.condition_reviewed_by
"""


async def list_monitoring_conditions(
    db: AsyncSession,
) -> list[dict]:
    the_result = await db.execute(
        text(
            """
            SELECT code, label, description
            FROM monitoring_condition
            WHERE is_selectable
            ORDER BY display_order, code
            """
        )
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]


async def get_monitoring_condition(
    db: AsyncSession,
    condition_code: str,
) -> dict | None:
    the_result = await db.execute(
        text(
            """
            SELECT monitoring_condition_id, code, label, is_selectable
            FROM monitoring_condition
            WHERE code = :condition_code
            """
        ),
        {"condition_code": condition_code},
    )

    the_row = the_result.mappings().first()

    return dict(the_row) if the_row is not None else None


async def save_follow_up(
    db: AsyncSession,
    report_reference: str,
    case_event_id: int,
    action_type_id: int,
    follow_up_type: str,
    follow_up_state: str,
    recording_level: str,
    action_date: date | None,
    responsible_team: str | None,
    source_reference: str | None,
    observations: str | None,
    recorded_outcome: str | None,
    notes: str | None,
    monitoring_condition_id: int | None,
    condition_reviewed_by: int | None,
    next_follow_up_required: bool,
    next_follow_up_date: date | None,
    supersedes_case_action_id: int | None,
    created_by: int,
    is_publishable: bool = False,
) -> dict | None:
    """
    Insert one follow-up record.

    Every shape rule is also a CHECK constraint or a trigger on the table, so
    a service bug cannot produce, say, a monitoring record with no condition.

    is_publishable defaults to false. Only the publication step sets it, so a
    new record or a correction is always private until someone publishes it.
    """

    the_result = await db.execute(
        text(
            """
            INSERT INTO case_action
                (report_id, case_event_id, action_type_id,
                 action_state, follow_up_type, recording_level,
                 action_date, responsible_team, source_reference,
                 observations, recorded_outcome, notes,
                 monitoring_condition_id, condition_reviewed_by,
                 next_follow_up_required, next_follow_up_date,
                 supersedes_case_action_id, created_by, is_publishable)

            SELECT
                r.report_id, :case_event_id, :action_type_id,
                :follow_up_state, :follow_up_type, :recording_level,
                :action_date, :responsible_team, :source_reference,
                :observations, :recorded_outcome, :notes,
                :monitoring_condition_id, :condition_reviewed_by,
                :next_follow_up_required, :next_follow_up_date,
                :supersedes_case_action_id, :created_by, :is_publishable

            FROM report AS r
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL

            RETURNING case_action_id
            """
        ),
        {
            "report_reference": report_reference,
            "case_event_id": case_event_id,
            "action_type_id": action_type_id,
            "follow_up_type": follow_up_type,
            "follow_up_state": follow_up_state,
            "recording_level": recording_level,
            "action_date": action_date,
            "responsible_team": responsible_team,
            "source_reference": source_reference,
            "observations": observations,
            "recorded_outcome": recorded_outcome,
            "notes": notes,
            "monitoring_condition_id": monitoring_condition_id,
            "condition_reviewed_by": condition_reviewed_by,
            "next_follow_up_required": next_follow_up_required,
            "next_follow_up_date": next_follow_up_date,
            "supersedes_case_action_id": supersedes_case_action_id,
            "created_by": created_by,
            "is_publishable": is_publishable,
        },
    )

    the_saved_id = the_result.scalar_one_or_none()

    if the_saved_id is None:
        return None

    return await get_follow_up(
        db=db,
        report_reference=report_reference,
        case_action_id=the_saved_id,
    )


async def get_follow_up(
    db: AsyncSession,
    report_reference: str,
    case_action_id: int,
) -> dict | None:
    """
    One follow-up record, scoped to its report so an id from another case
    cannot be read through this route.
    """

    the_result = await db.execute(
        text(
            THE_FOLLOW_UP_SELECT
            + """
            WHERE ca.case_action_id = :case_action_id
              AND r.report_reference = :report_reference
              AND r.deleted_at IS NULL
            """
        ),
        {
            "case_action_id": case_action_id,
            "report_reference": report_reference,
        },
    )

    the_row = the_result.mappings().first()

    return dict(the_row) if the_row is not None else None


async def list_follow_ups(
    db: AsyncSession,
    report_reference: str,
    include_superseded: bool = False,
) -> list[dict]:
    """
    Every follow-up on one case, oldest first, because a history reads
    forwards.

    Superseded records are hidden by default: the current picture is what a
    Coordinator wants, and the replaced rows are still there for audit.
    """

    the_result = await db.execute(
        text(
            THE_FOLLOW_UP_SELECT
            + """
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL
              AND (
                    :include_superseded
                    OR NOT EXISTS (
                        SELECT 1 FROM case_action AS later
                        WHERE later.supersedes_case_action_id = ca.case_action_id
                    )
                  )
            ORDER BY ca.action_date NULLS LAST, ca.created_at, ca.case_action_id
            """
        ),
        {
            "report_reference": report_reference,
            "include_superseded": include_superseded,
        },
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]


async def list_follow_up_evidence(
    db: AsyncSession,
    case_action_ids: list[int],
) -> dict[int, list[dict]]:
    """
    Safe evidence metadata for several follow-ups in one query, keyed by
    record. Evidence links to a follow-up through its case_event_id, which is
    how the Iteration 2 action evidence upload already stores it.
    """

    if not case_action_ids:
        return {}

    the_result = await db.execute(
        text(
            """
            SELECT ca.case_action_id,
                   e.evidence_id, e.media_type, e.file_size_bytes, e.uploaded_at
            FROM case_action AS ca
            JOIN evidence AS e ON e.case_event_id = ca.case_event_id
            WHERE ca.case_action_id = ANY(:case_action_ids)
            ORDER BY ca.case_action_id, e.display_order, e.evidence_id
            """
        ),
        {"case_action_ids": case_action_ids},
    )

    the_evidence_by_record: dict[int, list[dict]] = {}

    for the_row in the_result.mappings().all():
        the_item = dict(the_row)
        the_record_id = the_item.pop("case_action_id")

        the_evidence_by_record.setdefault(the_record_id, []).append(the_item)

    return the_evidence_by_record


async def count_completed_follow_ups(
    db: AsyncSession,
    report_reference: str,
) -> int:
    """
    How many completed actions or recorded outcomes a case has.

    US6.4 AC1 and the resolved_acted_on closure reason both need to know that
    something actually happened, as opposed to being planned.
    """

    the_result = await db.execute(
        text(
            """
            SELECT count(*)
            FROM case_action AS ca
            JOIN report AS r ON r.report_id = ca.report_id
            WHERE r.report_reference = :report_reference
              AND r.deleted_at IS NULL
              AND ca.action_state IN ('action_taken', 'outcome_recorded')
              AND NOT ca.is_demonstration
              AND NOT EXISTS (
                    SELECT 1 FROM case_action AS later
                    WHERE later.supersedes_case_action_id = ca.case_action_id
                  )
            """
        ),
        {"report_reference": report_reference},
    )

    return the_result.scalar_one()
