from datetime import (
    datetime,
    timezone,
)
from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest

from app.core.enums import (
    ActionState,
    CaseStatus,
)
from app.core.exceptions import (
    WorkflowStateError,
)
from app.repositories import (
    case_action_repository,
    queue_repository,
)
from app.services import (
    case_action_service,
    case_assessment_service,
)


NOW = datetime(
    2026,
    9,
    18,
    4,
    0,
    tzinfo=timezone.utc,
)


# ---------------------------------------------------------------------------
# API-15
#
# Non-terminal action-stage cases must remain visible in
# the active coordinator queue.
#
# Unclaimed received reports are intake-visible to all
# coordinators. Once claimed, an active case is visible
# only to its current owner.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api15_queue_keeps_action_stage_statuses_and_owner_scope():
    query_result = MagicMock()

    (
        query_result
        .mappings
        .return_value
        .all
        .return_value
    ) = []

    count_result = MagicMock()

    count_result.scalar_one.return_value = 0

    db = AsyncMock()

    db.execute.side_effect = [
        query_result,
        count_result,
    ]

    rows, total = (
        await queue_repository
        .list_incoming_reports(
            db=db,
            coordinator_id=42,
            page=1,
            page_size=20,
        )
    )

    assert rows == []
    assert total == 0

    assert (
        db.execute.await_count
        == 2
    )

    first_execute = (
        db.execute
        .await_args_list[0]
    )

    query_sql = str(
        first_execute.args[0]
    )

    query_params = (
        first_execute.args[1]
    )

    assert (
        "'response_recommended'"
        in query_sql
    )

    assert (
        "'response_planned'"
        in query_sql
    )

    assert (
        "'response_complete'"
        in query_sql
    )

    # Unclaimed intake path.
    assert (
        "claimed_by_user_id"
        in query_sql
    )

    assert (
        "IS NULL"
        in query_sql
    )

    # Owned active-case path.
    assert (
        ":coordinator_id"
        in query_sql
    )

    assert (
        query_params[
            "coordinator_id"
        ]
        == 42
    )

    assert (
        query_params[
            "limit"
        ]
        == 20
    )

    assert (
        query_params[
            "offset"
        ]
        == 0
    )


@pytest.mark.asyncio
async def test_api15_queue_count_uses_same_visibility_rules():
    query_result = MagicMock()

    (
        query_result
        .mappings
        .return_value
        .all
        .return_value
    ) = []

    count_result = MagicMock()

    count_result.scalar_one.return_value = 4

    db = AsyncMock()

    db.execute.side_effect = [
        query_result,
        count_result,
    ]

    _, total = (
        await queue_repository
        .list_incoming_reports(
            db=db,
            coordinator_id=77,
            page=2,
            page_size=10,
        )
    )

    assert total == 4

    second_execute = (
        db.execute
        .await_args_list[1]
    )

    count_sql = str(
        second_execute.args[0]
    )

    count_params = (
        second_execute.args[1]
    )

    assert (
        "'response_planned'"
        in count_sql
    )

    assert (
        "'response_complete'"
        in count_sql
    )

    assert (
        ":coordinator_id"
        in count_sql
    )

    assert (
        count_params[
            "coordinator_id"
        ]
        == 77
    )


# ---------------------------------------------------------------------------
# API-16
#
# Q1 usable = true
# Q2 credible = false
#
# is a valid US5.3 terminal outcome and must close the
# case as not substantiated without requiring a separate
# US5.4 response decision.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api16_not_credible_assessment_closes_not_substantiated(
    monkeypatch,
):
    fake_db = object()

    load_owned_case_mock = AsyncMock(
        return_value={
            "report_reference":
                "RC-0016",

            "claimed_by_user_id":
                42,

            "status_code":
                "under_review",
        }
    )

    save_assessment_mock = AsyncMock(
        return_value={
            "case_decision_id":
                501,

            "evidence_usable":
                True,

            "observation_credible":
                False,

            "decided_at":
                NOW,

            "coordinator_id":
                42,
        }
    )

    close_mock = AsyncMock(
        return_value={
            "report_reference":
                "RC-0016",

            "status":
                "closed_not_substantiated",

            "closure_reason_code":
                "not_substantiated",
        }
    )

    monkeypatch.setattr(
        case_assessment_service,
        "load_owned_case",
        load_owned_case_mock,
    )

    monkeypatch.setattr(
        case_assessment_service,
        "save_evidence_assessment",
        save_assessment_mock,
    )

    monkeypatch.setattr(
        case_assessment_service,
        (
            "close_not_substantiated_"
            "from_assessment"
        ),
        close_mock,
    )

    result = (
        await case_assessment_service
        .record_evidence_assessment(
            db=fake_db,
            report_reference=(
                "RC-0016"
            ),
            coordinator_id=42,
            evidence_usable=True,
            observation_credible=False,
            notes=(
                "The submitted evidence does "
                "not substantiate the report."
            ),
        )
    )

    assert (
        result[
            "report_reference"
        ]
        == "RC-0016"
    )

    assert (
        result[
            "evidence_usable"
        ]
        is True
    )

    assert (
        result[
            "observation_credible"
        ]
        is False
    )

    assert (
        result[
            "status"
        ]
        == "closed_not_substantiated"
    )

    assert (
        result[
            "assessed_at"
        ]
        == NOW
    )

    assert (
        result[
            "assessed_by"
        ]
        == 42
    )

    assessment_kwargs = (
        save_assessment_mock
        .await_args
        .kwargs
    )

    assert (
        assessment_kwargs[
            "db"
        ]
        is fake_db
    )

    assert (
        assessment_kwargs[
            "report_reference"
        ]
        == "RC-0016"
    )

    assert (
        assessment_kwargs[
            "coordinator_id"
        ]
        == 42
    )

    assert (
        assessment_kwargs[
            "evidence_usable"
        ]
        is True
    )

    assert (
        assessment_kwargs[
            "observation_credible"
        ]
        is False
    )

    close_mock.assert_awaited_once_with(
        db=fake_db,
        report_reference=(
            "RC-0016"
        ),
        coordinator_id=42,
        assessment_note=(
            "The submitted evidence does "
            "not substantiate the report."
        ),
    )


def test_api16_stale_assessment_reports_current_status():
    with pytest.raises(
        WorkflowStateError
    ) as captured_error:
        (
            case_assessment_service
            .validate_case_is_ready_for_assessment(
                current_status_code=(
                    "closed_not_substantiated"
                ),
            )
        )

    error = captured_error.value

    assert (
        error.status_code
        == 409
    )

    assert (
        error.current_status
        == "closed_not_substantiated"
    )

    assert (
        error.error_code
        == "invalid_workflow_state"
    )

    assert (
        "closed_not_substantiated"
        in error.message
    )


# ---------------------------------------------------------------------------
# API-17
#
# Action recorder identity must come from
# case_action.created_by.
#
# It must not be hardcoded to null and must not be replaced
# by the case's current owner.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api17_record_action_returns_original_recorder_name(
    monkeypatch,
):
    fake_db = object()

    monkeypatch.setattr(
        case_action_service,
        "load_owned_case",
        AsyncMock(
            return_value={
                "report_reference":
                    "RC-0017",

                "claimed_by_user_id":
                    42,

                "status_code":
                    (
                        CaseStatus
                        .RESPONSE_RECOMMENDED
                        .value
                    ),
            }
        ),
    )

    monkeypatch.setattr(
        case_action_service,
        "load_selectable_action_type",
        AsyncMock(
            return_value={
                "action_type_id":
                    3,

                "code":
                    "gear_removal",

                "label":
                    "Gear removal",

                "is_selectable":
                    True,
            }
        ),
    )

    monkeypatch.setattr(
        case_action_service,
        "validate_status_transition",
        AsyncMock(),
    )

    monkeypatch.setattr(
        case_action_service,
        "change_status",
        AsyncMock(
            return_value=(
                CaseStatus
                .RESPONSE_PLANNED
                .value
            )
        ),
    )

    monkeypatch.setattr(
        case_action_service,
        "get_latest_action_event_id",
        AsyncMock(
            return_value=901
        ),
    )

    save_action_mock = AsyncMock(
        return_value={
            "case_action_id":
                701,

            "case_event_id":
                901,

            "action_state":
                (
                    ActionState
                    .ACTION_PLANNED
                    .value
                ),

            "action_date":
                None,

            "responsible_team":
                "Marine Park Team",

            "notes":
                "Removal visit planned.",

            "created_by":
                42,

            "created_by_name":
                "Coordinator One",

            "created_at":
                NOW,
        }
    )

    monkeypatch.setattr(
        case_action_service,
        "save_case_action",
        save_action_mock,
    )

    result = (
        await case_action_service
        .record_action(
            db=fake_db,
            report_reference=(
                "RC-0017"
            ),
            coordinator_id=42,
            action_type_code=(
                "gear_removal"
            ),
            action_state=(
                ActionState
                .ACTION_PLANNED
                .value
            ),
            action_date=None,
            responsible_team=(
                "Marine Park Team"
            ),
            notes=(
                "Removal visit planned."
            ),
        )
    )

    assert (
        result[
            "case_action_id"
        ]
        == 701
    )

    assert (
        result[
            "case_event_id"
        ]
        == 901
    )

    assert (
        result[
            "created_by"
        ]
        == 42
    )

    assert (
        result[
            "created_by_name"
        ]
        == "Coordinator One"
    )

    assert (
        result[
            "status_code"
        ]
        == (
            CaseStatus
            .RESPONSE_PLANNED
            .value
        )
    )


@pytest.mark.asyncio
async def test_api17_action_insert_resolves_name_from_created_by():
    result = MagicMock()

    (
        result
        .mappings
        .return_value
        .first
        .return_value
    ) = {
        "case_action_id":
            701,

        "case_event_id":
            901,

        "action_state":
            "action_planned",

        "action_date":
            None,

        "responsible_team":
            "Marine Park Team",

        "notes":
            "Removal visit planned.",

        "created_by":
            42,

        "created_by_name":
            "Coordinator One",

        "created_at":
            NOW,
    }

    db = AsyncMock()

    db.execute.return_value = (
        result
    )

    saved = (
        await case_action_repository
        .save_case_action(
            db=db,
            report_reference=(
                "RC-0017"
            ),
            case_event_id=901,
            action_type_id=3,
            action_state=(
                "action_planned"
            ),
            action_date=None,
            responsible_team=(
                "Marine Park Team"
            ),
            notes=(
                "Removal visit planned."
            ),
            created_by=42,
        )
    )

    assert (
        saved[
            "created_by"
        ]
        == 42
    )

    assert (
        saved[
            "created_by_name"
        ]
        == "Coordinator One"
    )

    execute_call = (
        db.execute.await_args
    )

    sql = str(
        execute_call.args[0]
    )

    # Critical API-17 regression check:
    # resolve the display name from the immutable action
    # recorder identity, not report.claimed_by_user_id.
    assert (
        "ia.created_by"
        in sql
    )

    assert (
        "u.display_name"
        in sql
    )


@pytest.mark.asyncio
async def test_api17_action_history_resolves_name_from_original_recorder():
    result = MagicMock()

    (
        result
        .mappings
        .return_value
        .all
        .return_value
    ) = []

    db = AsyncMock()

    db.execute.return_value = (
        result
    )

    rows = (
        await case_action_repository
        .list_case_actions(
            db=db,
            report_reference=(
                "RC-0017"
            ),
        )
    )

    assert rows == []

    execute_call = (
        db.execute.await_args
    )

    sql = str(
        execute_call.args[0]
    )

    assert (
        "ca.created_by"
        in sql
    )

    assert (
        "u.display_name"
        in sql
    )

    # Protect against a future shortcut that accidentally
    # labels an old action with whoever owns the case now.
    assert (
        "u.user_id ="
        in sql
    )

    assert (
        "ca.created_by"
        in sql
    )