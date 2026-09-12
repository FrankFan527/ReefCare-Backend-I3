# ---------------------------------------------------------------------------
# Conservation action policy (US7.1).
#
# Services decide whether an action is allowed; repositories carry it out.
#
# SECURITY NOTE: reefcare_change_status() records p_actor_user_id in the audit
# event but does not check that the actor owns the case. load_owned_case() is
# therefore the only thing preventing one coordinator recording an action on
# another coordinator's case, exactly as it is for the information request in
# case_workflow_service.
#
# The state model follows US7.1 AC1, Evidence Accepted -> Action Planned ->
# Action Taken, mapped onto the statuses PostgreSQL already seeds:
#
#   response_recommended  reached by the US5.4 intervention_required decision
#     -> action_planned   moves the case to response_planned
#     -> action_taken     moves the case to response_complete
#
# A case may carry more than one action. Recording a second planned action
# while the case already sits in response_planned is legitimate: a coordinator
# may plan both a gear removal and an authority notification. The action is
# therefore recorded without a status move rather than rejected.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActionState, CaseStatus
from app.core.exceptions import DomainValidationError, WorkflowError
from app.repositories.case_action_repository import (
    get_action_type,
    get_latest_action_event_id,
    insert_standalone_action_event,
    list_case_actions,
    list_selectable_action_types,
    save_case_action,
)
from app.repositories.case_repository import change_status
from app.services.case_workflow_service import (
    load_owned_case,
    validate_status_transition,
)


# case_event.event_type for an action. Mirrors the repository constant so the
# service can pass it to reefcare_change_status().
ACTION_EVENT_TYPE: str = "action_recorded"


# The status a case reaches once the action is recorded.
STATUS_FOR_ACTION_STATE: dict[str, str] = {
    ActionState.ACTION_PLANNED.value: CaseStatus.RESPONSE_PLANNED.value,
    ActionState.ACTION_TAKEN.value: CaseStatus.RESPONSE_COMPLETE.value,
}


# The statuses a case may be in before each action state is allowed.
#
# action_planned accepts a case already in response_planned so a second planned
# action is recorded rather than refused. action_taken accepts a case already
# in response_complete for the same reason.
PERMITTED_STATUSES_FOR_ACTION_STATE: dict[str, set[str]] = {
    ActionState.ACTION_PLANNED.value: {
        CaseStatus.RESPONSE_RECOMMENDED.value,
        CaseStatus.RESPONSE_PLANNED.value,
    },
    ActionState.ACTION_TAKEN.value: {
        CaseStatus.RESPONSE_PLANNED.value,
        CaseStatus.RESPONSE_COMPLETE.value,
    },
}


def validate_action_state_against_case(
    action_state: str,
    current_status_code: str,
) -> None:
    """
    Check the action against the case's current status before anything is
    written.

    An early-feedback check only. reefcare_guard_status_change() remains
    authoritative and will reject an unlisted transition regardless of what
    this concludes.

    The error names the status the case is actually in, because a coordinator
    who reaches this has almost always tried to record an action on a case that
    has not yet had an intervention_required decision.
    """

    the_permitted_statuses = PERMITTED_STATUSES_FOR_ACTION_STATE.get(
        action_state
    )

    if the_permitted_statuses is None:
        raise DomainValidationError(
            f"Unknown action state: {action_state}"
        )

    if current_status_code not in the_permitted_statuses:
        raise WorkflowError(
            f"An action cannot be recorded while the case is "
            f"{current_status_code}. Record an Intervention Required "
            f"decision first."
        )


async def load_selectable_action_type(
    db: AsyncSession,
    action_type_code: str,
) -> dict:
    """
    Resolve the action type code and confirm it may currently be chosen.
    """

    the_action_type = await get_action_type(
        db=db,
        action_type_code=action_type_code,
    )

    if the_action_type is None:
        raise DomainValidationError(
            f"Unknown action type: {action_type_code}"
        )

    if not the_action_type["is_selectable"]:
        raise WorkflowError(
            f"Action type {action_type_code} is not currently selectable"
        )

    return the_action_type


async def record_action(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    action_type_code: str,
    action_state: str,
    action_date: date | None,
    responsible_team: str | None,
    notes: str | None,
) -> dict:
    """
    Record one conservation action against a case this coordinator owns.

    Order matters. Ownership is checked before anything else, so a coordinator
    who does not own the case learns nothing about its current state.

    Whether the case status moves depends on where it already is. If it needs
    to move, reefcare_change_status() writes both the status and the
    action_recorded event in one transaction, and the event is located
    afterwards. If the case already sits in the target status, a standalone
    event is written instead, which keeps the action traceable without
    repeating an observer-facing status entry that has already been shown.

    The caller commits.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    validate_action_state_against_case(
        action_state=action_state,
        current_status_code=the_case["status_code"],
    )

    the_action_type = await load_selectable_action_type(
        db=db,
        action_type_code=action_type_code,
    )

    the_target_status = STATUS_FOR_ACTION_STATE[action_state]
    the_case_moves = the_case["status_code"] != the_target_status

    if the_case_moves:
        await validate_status_transition(
            db=db,
            from_status_code=the_case["status_code"],
            to_status_code=the_target_status,
        )

        the_resulting_status = await change_status(
            db=db,
            report_reference=report_reference,
            status_code=the_target_status,
            actor_user_id=coordinator_id,
            note=notes,
            event_type=ACTION_EVENT_TYPE,
        )

        the_case_event_id = await get_latest_action_event_id(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
        )

    else:
        the_resulting_status = the_case["status_code"]

        the_case_event_id = await insert_standalone_action_event(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            note=notes,
        )

    the_saved_action = await save_case_action(
        db=db,
        report_reference=report_reference,
        case_event_id=the_case_event_id,
        action_type_id=the_action_type["action_type_id"],
        action_state=action_state,
        action_date=action_date,
        responsible_team=responsible_team,
        notes=notes,
        created_by=coordinator_id,
    )

    return {
        "case_action_id": the_saved_action["case_action_id"],
        "report_reference": report_reference,

        "action_type_code": the_action_type["code"],
        "action_type_label": the_action_type["label"],

        "action_state": the_saved_action["action_state"],
        "action_date": the_saved_action["action_date"],

        "responsible_team": the_saved_action["responsible_team"],
        "notes": the_saved_action["notes"],

        "status_code": the_resulting_status,

        "created_by": the_saved_action["created_by"],
        "created_by_name": None,
        "created_at": the_saved_action["created_at"],
    }


async def list_actions_for_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> list[dict]:
    """
    Return every action recorded against a case this coordinator owns.

    Ownership is verified before any action detail is returned. An action
    record names a responsible team and describes what a conservation partner
    did or intends to do, which is not queue-safe information.
    """

    await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    return await list_case_actions(
        db=db,
        report_reference=report_reference,
    )


async def list_action_type_options(
    db: AsyncSession,
) -> list[dict]:
    """
    Return the action type vocabulary for the coordinator interface.
    """

    return await list_selectable_action_types(db=db)