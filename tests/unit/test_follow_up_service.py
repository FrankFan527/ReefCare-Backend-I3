# ---------------------------------------------------------------------------
# US7.1 / US7.2 follow-up — unit tests (no database).
#
# Covers the rules that live in Python: when a follow-up may be recorded,
# which states move the case, the request validation that keeps the three
# follow-up kinds distinct, and the honest empty state.
# ---------------------------------------------------------------------------

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import (
    AuthorizationError,
    DomainValidationError,
    NotFoundError,
    WorkflowError,
)
from app.schemas.follow_up import (
    FollowUpCorrection,
    FollowUpCreate,
    FollowUpState,
    FollowUpType,
    MonitoringCreate,
)
from app.services import follow_up_service as the_service


THE_TODAY = date(2026, 10, 4)


# ---------------------------------------------------------------------------
# US7.1 AC1 / US7.2 AC1 — a follow-up needs an assessed case
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "the_status",
    ["draft", "submitted", "received", "claimed", "under_review", "needs_more_info"],
)
def test_follow_up_refused_before_assessment(the_status):
    with pytest.raises(WorkflowError):
        the_service.assert_case_is_assessed(the_status)


@pytest.mark.parametrize(
    "the_status",
    ["evidence_accepted", "monitoring", "referred", "response_recommended",
     "response_planned", "response_complete", "closed_logged"],
)
def test_follow_up_allowed_once_assessed(the_status):
    the_service.assert_case_is_assessed(the_status)


# ---------------------------------------------------------------------------
# US7.1 AC4 — planned and completed stay distinct
# ---------------------------------------------------------------------------

def test_planned_action_needs_an_intervention_decision():
    the_service.assert_action_state_fits_case("action_planned", "response_recommended")

    with pytest.raises(WorkflowError):
        the_service.assert_action_state_fits_case("action_planned", "monitoring")


def test_completed_action_follows_a_planned_one():
    the_service.assert_action_state_fits_case("action_taken", "response_planned")

    with pytest.raises(WorkflowError):
        the_service.assert_action_state_fits_case("action_taken", "response_recommended")


def test_unknown_state_is_a_validation_error():
    with pytest.raises(DomainValidationError):
        the_service.assert_action_state_fits_case("invented_state", "response_planned")


# ---------------------------------------------------------------------------
# US7.2 AC1 — monitoring fits a narrower set of statuses
# ---------------------------------------------------------------------------

def test_monitoring_allowed_on_a_monitoring_case():
    the_service.assert_monitoring_fits_case("monitoring")
    the_service.assert_monitoring_fits_case("evidence_accepted")


def test_monitoring_refused_on_a_referred_case():
    # a referral is awaiting an external outcome, not a ReefCare visit
    with pytest.raises(WorkflowError):
        the_service.assert_monitoring_fits_case("referred")


# ---------------------------------------------------------------------------
# Request validation — the three kinds stay distinct
# ---------------------------------------------------------------------------

def test_state_must_match_the_follow_up_type():
    with pytest.raises(ValidationError):
        FollowUpCreate(
            follow_up_type=FollowUpType.SOURCED_OUTCOME,
            follow_up_state=FollowUpState.ACTION_TAKEN,
            action_type_code="gear_removal",
        )


def test_monitoring_is_refused_on_the_follow_up_route():
    # US7.2 has its own route because it needs a condition and a next-visit state
    with pytest.raises(ValidationError):
        FollowUpCreate(
            follow_up_type=FollowUpType.MONITORING,
            follow_up_state=FollowUpState.MONITORING_RECORDED,
            action_type_code="site_monitoring",
        )


def test_sourced_outcome_needs_a_source_and_an_outcome():
    with pytest.raises(ValidationError):
        FollowUpCreate(
            follow_up_type=FollowUpType.SOURCED_OUTCOME,
            follow_up_state=FollowUpState.OUTCOME_RECORDED,
            action_type_code="authority_notified",
            action_date=THE_TODAY,
            recorded_outcome="Gear removed",
        )

    the_request = FollowUpCreate(
        follow_up_type=FollowUpType.SOURCED_OUTCOME,
        follow_up_state=FollowUpState.OUTCOME_RECORDED,
        action_type_code="authority_notified",
        action_date=THE_TODAY,
        source_reference="Tioman Marine Park office, email 2026-10-01",
        recorded_outcome="Gear removed by park team",
    )

    assert the_request.recording_level.value == "coordinator_summary"


def test_completed_action_needs_a_date():
    with pytest.raises(ValidationError):
        FollowUpCreate(
            follow_up_type=FollowUpType.ACTION,
            follow_up_state=FollowUpState.ACTION_TAKEN,
            action_type_code="gear_removal",
        )


# ---------------------------------------------------------------------------
# US7.2 AC2 — no invented next visit
# ---------------------------------------------------------------------------

def test_no_follow_up_scheduled_is_a_valid_answer():
    the_request = MonitoringCreate(
        action_date=THE_TODAY,
        condition_code="stable",
        observations="No change since the last visit",
    )

    assert the_request.next_follow_up_required is False
    assert the_request.next_follow_up_date is None


def test_a_date_without_a_required_follow_up_is_refused():
    with pytest.raises(ValidationError):
        MonitoringCreate(
            action_date=THE_TODAY,
            condition_code="stable",
            observations="No change",
            next_follow_up_required=False,
            next_follow_up_date=THE_TODAY + timedelta(days=30),
        )


def test_the_next_visit_cannot_precede_this_one():
    with pytest.raises(ValidationError):
        MonitoringCreate(
            action_date=THE_TODAY,
            condition_code="deteriorating",
            observations="Worse than last time",
            next_follow_up_required=True,
            next_follow_up_date=THE_TODAY - timedelta(days=1),
        )


def test_camel_case_monitoring_request_is_accepted():
    the_request = MonitoringCreate.model_validate(
        {
            "actionDate": "2026-10-04",
            "conditionCode": "improving",
            "observations": "Coral recovering",
            "nextFollowUpRequired": True,
            "nextFollowUpDate": "2026-12-01",
        }
    )

    assert the_request.condition_code == "improving"
    assert the_request.next_follow_up_date == date(2026, 12, 1)


# ---------------------------------------------------------------------------
# Ownership and the empty state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_listing_requires_ownership_first(monkeypatch):
    the_owner_check = AsyncMock(side_effect=AuthorizationError("not yours"))
    the_list = AsyncMock()

    monkeypatch.setattr(the_service, "load_owned_case", the_owner_check)
    monkeypatch.setattr(the_service.the_repository, "list_follow_ups", the_list)

    with pytest.raises(AuthorizationError):
        await the_service.list_follow_ups_for_owned_case(AsyncMock(), "RC-0001", 42)

    the_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_history_says_so(monkeypatch):
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(
        the_service.the_repository, "list_follow_ups", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        the_service.the_repository, "list_follow_up_evidence", AsyncMock(return_value={})
    )

    the_response = await the_service.list_follow_ups_for_owned_case(
        AsyncMock(), "RC-0001", 42
    )

    assert the_response.total == 0
    assert the_response.items == []
    assert "no follow-up" in the_response.message.lower()


@pytest.mark.asyncio
async def test_missing_follow_up_is_not_found(monkeypatch):
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(
        the_service.the_repository, "get_follow_up", AsyncMock(return_value=None)
    )

    with pytest.raises(NotFoundError):
        await the_service.get_follow_up_for_owned_case(AsyncMock(), "RC-0001", 99, 42)


# ---------------------------------------------------------------------------
# US7.1 AC8 — correction by supersession
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_already_corrected_record_cannot_be_corrected_again(monkeypatch):
    monkeypatch.setattr(
        the_service, "load_owned_case",
        AsyncMock(return_value={"status_code": "response_planned"}),
    )
    monkeypatch.setattr(
        the_service.the_repository, "get_follow_up",
        AsyncMock(return_value={
            "follow_up_type": "action",
            "follow_up_state": "action_planned",
            "superseded_by_case_action_id": 77,
        }),
    )

    with pytest.raises(WorkflowError):
        await the_service.correct_follow_up(
            AsyncMock(), "RC-0001", 12, 42,
            FollowUpCorrection(correction_reason="wrong team"),
        )


@pytest.mark.asyncio
async def test_a_monitoring_visit_is_not_corrected_in_place(monkeypatch):
    monkeypatch.setattr(
        the_service, "load_owned_case",
        AsyncMock(return_value={"status_code": "monitoring"}),
    )
    monkeypatch.setattr(
        the_service.the_repository, "get_follow_up",
        AsyncMock(return_value={
            "follow_up_type": "monitoring",
            "follow_up_state": "monitoring_recorded",
            "superseded_by_case_action_id": None,
        }),
    )

    with pytest.raises(WorkflowError):
        await the_service.correct_follow_up(
            AsyncMock(), "RC-0001", 12, 42,
            FollowUpCorrection(correction_reason="wrong date"),
        )
