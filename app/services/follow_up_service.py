# ---------------------------------------------------------------------------
# US7.1 Conservation follow-up and US7.2 follow-up monitoring — policy.
#
# Every entry point starts with load_owned_case(), so a Coordinator who does
# not own the case cannot read or write its follow-up history.
#
# Case status and follow-up records are kept apart on purpose:
#
#   an ACTION moves the case, reusing the Iteration 2 chain
#   response_recommended -> response_planned -> response_complete (US7.1 AC4)
#
#   MONITORING and a SOURCED OUTCOME move nothing. A monitoring visit can
#   repeat without forcing a schedule (US7.2 AC2), and a referral stays a
#   referral until a Coordinator decides otherwise (US7.1 AC5)
# ---------------------------------------------------------------------------

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import (
    DatabaseOperationError,
    DomainValidationError,
    NotFoundError,
    WorkflowError,
)
from app.repositories import follow_up_repository as the_repository
from app.repositories.case_action_repository import (
    get_action_type,
    get_latest_action_event_id,
    insert_standalone_action_event,
)
from app.repositories.case_repository import change_status
from app.schemas.follow_up import (
    FollowUpCorrection,
    FollowUpCreate,
    FollowUpEvidenceSummary,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpState,
    FollowUpType,
    MonitoringConditionOption,
    MonitoringCreate,
)
from app.services.case_workflow_service import (
    load_owned_case,
    validate_status_transition,
)


# the action type used for a monitoring visit, already seeded in Iteration 2
THE_MONITORING_ACTION_TYPE_CODE: str = "site_monitoring"


# US7.1 AC1. A follow-up belongs to a case that has been assessed and given a
# response decision. The same rule is a trigger on case_action; this check
# exists so the API can say why rather than surfacing a database error.
THE_STATUSES_BEFORE_ASSESSMENT: frozenset[str] = frozenset({
    CaseStatus.DRAFT.value,
    CaseStatus.SUBMITTED.value,
    CaseStatus.RECEIVED.value,
    CaseStatus.CLAIMED.value,
    CaseStatus.UNDER_REVIEW.value,
    CaseStatus.NEEDS_MORE_INFO.value,
})


# only an action moves the case, and only from these statuses
THE_STATUS_FOR_ACTION_STATE: dict[str, str] = {
    FollowUpState.ACTION_PLANNED.value: CaseStatus.RESPONSE_PLANNED.value,
    FollowUpState.ACTION_TAKEN.value: CaseStatus.RESPONSE_COMPLETE.value,
}

THE_PERMITTED_STATUSES_FOR_ACTION_STATE: dict[str, set[str]] = {
    FollowUpState.ACTION_PLANNED.value: {
        CaseStatus.RESPONSE_RECOMMENDED.value,
        CaseStatus.RESPONSE_PLANNED.value,
    },
    FollowUpState.ACTION_TAKEN.value: {
        CaseStatus.RESPONSE_PLANNED.value,
        CaseStatus.RESPONSE_COMPLETE.value,
    },
}


# US7.2 AC1. Monitoring is appropriate once the case has reached one of these.
THE_PERMITTED_STATUSES_FOR_MONITORING: frozenset[str] = frozenset({
    CaseStatus.EVIDENCE_ACCEPTED.value,
    CaseStatus.MONITORING.value,
    CaseStatus.RESPONSE_RECOMMENDED.value,
    CaseStatus.RESPONSE_PLANNED.value,
    CaseStatus.RESPONSE_COMPLETE.value,
    CaseStatus.CLOSED_LOGGED.value,
    CaseStatus.CLOSED_RESOLVED.value,
})


THE_EMPTY_HISTORY_MESSAGE: str = (
    "No follow-up, monitoring visit or external outcome has been recorded "
    "for this case yet."
)


# ---------------------------------------------------------------------------
# Small pure helpers, unit-tested without a database
# ---------------------------------------------------------------------------

def assert_case_is_assessed(
    the_status_code: str,
) -> None:
    """
    US7.1 AC1 and US7.2 AC1.
    """

    if the_status_code in THE_STATUSES_BEFORE_ASSESSMENT:
        raise WorkflowError(
            f"A follow-up cannot be recorded while the case is {the_status_code}. "
            "Record the evidence assessment and response decision first."
        )


def assert_action_state_fits_case(
    the_follow_up_state: str,
    the_status_code: str,
) -> None:
    the_permitted = THE_PERMITTED_STATUSES_FOR_ACTION_STATE.get(the_follow_up_state)

    if the_permitted is None:
        raise DomainValidationError(f"Unknown follow-up state: {the_follow_up_state}")

    if the_status_code not in the_permitted:
        raise WorkflowError(
            f"An action cannot be recorded while the case is {the_status_code}. "
            "Record an Intervention Required decision first."
        )


def correction_moves_case(
    the_follow_up_type: str,
    the_original_state: str,
    the_corrected_state: str,
    the_status_code: str,
) -> bool:
    """
    US7.1 AC8. A correction restates facts about an existing record; it is not
    a new action. So the new-action status rule only applies when the
    correction actually changes an action's state, and an unchanged state is
    accepted whatever the case has moved on to since (QA-E7-01).

    Returns True when the corrected state should move the case forward.
    """

    if (
        the_follow_up_type != FollowUpType.ACTION.value
        or the_corrected_state == the_original_state
    ):
        return False

    # the case cannot be moved backwards by a correction
    if (
        the_original_state == FollowUpState.ACTION_TAKEN.value
        and the_corrected_state == FollowUpState.ACTION_PLANNED.value
    ):
        raise WorkflowError(
            "A taken action cannot be corrected back to planned. "
            "Record a new planned action instead."
        )

    assert_action_state_fits_case(
        the_follow_up_state=the_corrected_state,
        the_status_code=the_status_code,
    )

    return THE_STATUS_FOR_ACTION_STATE.get(the_corrected_state) != the_status_code


def assert_monitoring_fits_case(
    the_status_code: str,
) -> None:
    if the_status_code not in THE_PERMITTED_STATUSES_FOR_MONITORING:
        raise WorkflowError(
            f"A monitoring visit cannot be recorded while the case is {the_status_code}."
        )


def to_follow_up_response(
    the_row: dict,
    the_evidence: list[dict] | None = None,
) -> FollowUpResponse:
    return FollowUpResponse(
        **{
            the_key: the_value
            for the_key, the_value in the_row.items()
            if the_key != "evidence"
        },
        evidence=[
            FollowUpEvidenceSummary(**the_item)
            for the_item in (the_evidence or [])
        ],
    )


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

async def list_monitoring_condition_options(
    db: AsyncSession,
) -> list[MonitoringConditionOption]:
    the_rows = await the_repository.list_monitoring_conditions(db=db)

    return [MonitoringConditionOption(**the_row) for the_row in the_rows]


# ---------------------------------------------------------------------------
# US7.1 AC7 — read
# ---------------------------------------------------------------------------

async def list_follow_ups_for_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    include_superseded: bool = False,
) -> FollowUpListResponse:
    """
    The case's follow-up history. An empty history says so plainly rather
    than leaving the caller to infer that work happened.
    """

    await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    the_rows = await the_repository.list_follow_ups(
        db=db,
        report_reference=report_reference,
        include_superseded=include_superseded,
    )

    the_evidence = await the_repository.list_follow_up_evidence(
        db=db,
        case_action_ids=[the_row["case_action_id"] for the_row in the_rows],
    )

    return FollowUpListResponse(
        report_reference=report_reference,
        items=[
            to_follow_up_response(
                the_row,
                the_evidence.get(the_row["case_action_id"], []),
            )
            for the_row in the_rows
        ],
        total=len(the_rows),
        message=None if the_rows else THE_EMPTY_HISTORY_MESSAGE,
    )


async def get_follow_up_for_owned_case(
    db: AsyncSession,
    report_reference: str,
    case_action_id: int,
    coordinator_id: int,
) -> FollowUpResponse:
    await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    the_row = await the_repository.get_follow_up(
        db=db,
        report_reference=report_reference,
        case_action_id=case_action_id,
    )

    if the_row is None:
        raise NotFoundError(
            f"Follow-up {case_action_id} was not found on report {report_reference}"
        )

    the_evidence = await the_repository.list_follow_up_evidence(
        db=db,
        case_action_ids=[case_action_id],
    )

    return to_follow_up_response(the_row, the_evidence.get(case_action_id, []))


# ---------------------------------------------------------------------------
# US7.1 — create
# ---------------------------------------------------------------------------

async def record_follow_up(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    the_request: FollowUpCreate,
) -> FollowUpResponse:
    """
    Record an action or a sourced external outcome.

    An action moves the case; a sourced outcome never does, so a referral is
    not turned into an accepted or completed action (AC5).
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    assert_case_is_assessed(the_case["status_code"])

    the_action_type = await _load_selectable_action_type(
        db=db,
        action_type_code=the_request.action_type_code,
    )

    the_case_moves = the_request.follow_up_type == FollowUpType.ACTION

    if the_case_moves:
        assert_action_state_fits_case(
            the_follow_up_state=the_request.follow_up_state.value,
            the_status_code=the_case["status_code"],
        )

    try:
        the_case_event_id = await _open_history_event(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            note=the_request.notes,
            the_target_status=(
                THE_STATUS_FOR_ACTION_STATE[the_request.follow_up_state.value]
                if the_case_moves
                else None
            ),
            the_current_status=the_case["status_code"],
        )

        the_saved = await the_repository.save_follow_up(
            db=db,
            report_reference=report_reference,
            case_event_id=the_case_event_id,
            action_type_id=the_action_type["action_type_id"],
            follow_up_type=the_request.follow_up_type.value,
            follow_up_state=the_request.follow_up_state.value,
            recording_level=the_request.recording_level.value,
            action_date=the_request.action_date,
            responsible_team=_clean(the_request.responsible_team),
            source_reference=_clean(the_request.source_reference),
            observations=None,
            recorded_outcome=_clean(the_request.recorded_outcome),
            notes=_clean(the_request.notes),
            monitoring_condition_id=None,
            condition_reviewed_by=None,
            next_follow_up_required=False,
            next_follow_up_date=None,
            supersedes_case_action_id=None,
            created_by=coordinator_id,
        )

        if the_saved is None:
            raise DatabaseOperationError("The follow-up could not be recorded")

        await db.commit()

    except SQLAlchemyError as the_error:
        await db.rollback()
        raise DatabaseOperationError(
            "The follow-up could not be recorded"
        ) from the_error

    return to_follow_up_response(the_saved)


# ---------------------------------------------------------------------------
# US7.2 — monitoring
# ---------------------------------------------------------------------------

async def record_monitoring(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    the_request: MonitoringCreate,
) -> FollowUpResponse:
    """
    Record a dated monitoring visit with a human-reviewed condition.

    The case does not move. Monitoring may repeat as often as the site needs
    it, and a visit may close with no next date scheduled (AC2).
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    assert_case_is_assessed(the_case["status_code"])
    assert_monitoring_fits_case(the_case["status_code"])

    the_condition = await the_repository.get_monitoring_condition(
        db=db,
        condition_code=the_request.condition_code,
    )

    if the_condition is None:
        raise DomainValidationError(
            f"Unknown monitoring condition: {the_request.condition_code}"
        )

    if not the_condition["is_selectable"]:
        raise WorkflowError(
            f"Monitoring condition {the_request.condition_code} "
            "is not currently selectable"
        )

    the_action_type = await _load_selectable_action_type(
        db=db,
        action_type_code=THE_MONITORING_ACTION_TYPE_CODE,
    )

    try:
        the_case_event_id = await insert_standalone_action_event(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            note=the_request.notes,
        )

        the_saved = await the_repository.save_follow_up(
            db=db,
            report_reference=report_reference,
            case_event_id=the_case_event_id,
            action_type_id=the_action_type["action_type_id"],
            follow_up_type=FollowUpType.MONITORING.value,
            follow_up_state=FollowUpState.MONITORING_RECORDED.value,
            recording_level=the_request.recording_level.value,
            action_date=the_request.action_date,
            responsible_team=_clean(the_request.responsible_team),
            source_reference=None,
            observations=the_request.observations.strip(),
            recorded_outcome=None,
            notes=_clean(the_request.notes),
            monitoring_condition_id=the_condition["monitoring_condition_id"],
            # the reviewer is the acting Coordinator: the condition is a human
            # judgement and is recorded as that person's (US7.2 AC4)
            condition_reviewed_by=coordinator_id,
            next_follow_up_required=the_request.next_follow_up_required,
            next_follow_up_date=the_request.next_follow_up_date,
            supersedes_case_action_id=None,
            created_by=coordinator_id,
        )

        if the_saved is None:
            raise DatabaseOperationError("The monitoring record could not be saved")

        await db.commit()

    except SQLAlchemyError as the_error:
        await db.rollback()
        raise DatabaseOperationError(
            "The monitoring record could not be saved"
        ) from the_error

    return to_follow_up_response(the_saved)


# ---------------------------------------------------------------------------
# US7.1 AC8 — correction by supersession
# ---------------------------------------------------------------------------

async def correct_follow_up(
    db: AsyncSession,
    report_reference: str,
    case_action_id: int,
    coordinator_id: int,
    the_request: FollowUpCorrection,
) -> FollowUpResponse:
    """
    Append a corrected copy of an existing record.

    Nothing is overwritten: the original stays in the history and the new row
    points back at it, so who recorded what and when is never lost.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    the_original = await the_repository.get_follow_up(
        db=db,
        report_reference=report_reference,
        case_action_id=case_action_id,
    )

    if the_original is None:
        raise NotFoundError(
            f"Follow-up {case_action_id} was not found on report {report_reference}"
        )

    if the_original["superseded_by_case_action_id"] is not None:
        raise WorkflowError(
            "This record has already been corrected. "
            "Correct the most recent version instead."
        )

    if the_original["follow_up_type"] == FollowUpType.MONITORING.value:
        raise WorkflowError(
            "A monitoring visit is a dated observation and is not corrected in place. "
            "Record a new monitoring visit instead."
        )

    the_state = (
        the_request.follow_up_state.value
        if the_request.follow_up_state is not None
        else the_original["follow_up_state"]
    )

    the_date = (
        the_request.action_date
        if the_request.action_date is not None
        else the_original["action_date"]
    )

    if the_state == FollowUpState.ACTION_TAKEN.value and the_date is None:
        raise DomainValidationError(
            "actionDate is required when followUpState is action_taken"
        )

    # only an action has a state a Coordinator may restate
    if (
        the_original["follow_up_type"] != FollowUpType.ACTION.value
        and the_state != the_original["follow_up_state"]
    ):
        raise DomainValidationError(
            "followUpState can only be corrected on an action record"
        )

    the_case_moves = correction_moves_case(
        the_follow_up_type=the_original["follow_up_type"],
        the_original_state=the_original["follow_up_state"],
        the_corrected_state=the_state,
        the_status_code=the_case["status_code"],
    )

    the_action_type = await _load_selectable_action_type(
        db=db,
        action_type_code=the_original["action_type_code"],
    )

    the_note = _clean(the_request.notes) or the_original["notes"]
    the_correction_note = (
        f"{the_note or ''}\n\nCorrection: {the_request.correction_reason.strip()}"
    ).strip()

    try:
        the_case_event_id = await _open_history_event(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            note=the_correction_note,
            the_target_status=(
                THE_STATUS_FOR_ACTION_STATE[the_state] if the_case_moves else None
            ),
            the_current_status=the_case["status_code"],
        )

        the_saved = await the_repository.save_follow_up(
            db=db,
            report_reference=report_reference,
            case_event_id=the_case_event_id,
            action_type_id=the_action_type["action_type_id"],
            follow_up_type=the_original["follow_up_type"],
            follow_up_state=the_state,
            recording_level=the_original["recording_level"],
            action_date=the_date,
            responsible_team=(
                _clean(the_request.responsible_team)
                or the_original["responsible_team"]
            ),
            source_reference=the_original["source_reference"],
            observations=the_original["observations"],
            recorded_outcome=(
                _clean(the_request.recorded_outcome)
                or the_original["recorded_outcome"]
            ),
            notes=the_correction_note,
            monitoring_condition_id=None,
            condition_reviewed_by=None,
            next_follow_up_required=False,
            next_follow_up_date=None,
            supersedes_case_action_id=case_action_id,
            created_by=coordinator_id,
        )

        if the_saved is None:
            raise DatabaseOperationError("The correction could not be recorded")

        await db.commit()

    except SQLAlchemyError as the_error:
        await db.rollback()
        raise DatabaseOperationError(
            "The correction could not be recorded"
        ) from the_error

    return to_follow_up_response(the_saved)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _clean(the_value: str | None) -> str | None:
    return (the_value or "").strip() or None


async def _load_selectable_action_type(
    db: AsyncSession,
    action_type_code: str,
) -> dict:
    the_action_type = await get_action_type(db=db, action_type_code=action_type_code)

    if the_action_type is None:
        raise DomainValidationError(f"Unknown action type: {action_type_code}")

    if not the_action_type["is_selectable"]:
        raise WorkflowError(
            f"Action type {action_type_code} is not currently selectable"
        )

    return the_action_type


async def _open_history_event(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    note: str | None,
    the_target_status: str | None,
    the_current_status: str,
) -> int:
    """
    Every follow-up hangs off a case_event, which is what the Observer
    timeline and the evidence upload both key on.

    When the record moves the case, the event is the status change itself, so
    the history shows one event rather than two.
    """

    if the_target_status is not None and the_target_status != the_current_status:
        await validate_status_transition(
            db=db,
            from_status_code=the_current_status,
            to_status_code=the_target_status,
        )

        await change_status(
            db=db,
            report_reference=report_reference,
            status_code=the_target_status,
            actor_user_id=coordinator_id,
            note=note,
            event_type="action_recorded",
        )

        the_event_id = await get_latest_action_event_id(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
        )

        if the_event_id is None:
            raise DatabaseOperationError(
                "The follow-up history event could not be resolved"
            )

        return the_event_id

    return await insert_standalone_action_event(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
        note=note,
    )
