# ---------------------------------------------------------------------------
# US8.1 Coordinator site history — unit tests (no database).
#
# The rules that matter here are about what the history claims: assessment
# states stay distinct, a thin history says so, and nothing private leaks
# into a view other Coordinators can open.
# ---------------------------------------------------------------------------

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.site_history import (
    AssessmentState,
    SiteHistoryRecordType,
    SiteHistoryState,
)
from app.services import site_history_service as the_service


THE_NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def make_observation(
    the_state: str = "evidence_accepted",
    the_owned: bool = True,
    the_reference: str = "RC-0001",
    the_day: int = 1,
) -> dict:
    return {
        "report_reference": the_reference,
        "owned_by_you": the_owned,
        "threat_category_code": "ghost_gear",
        "threat_category_label": "Ghost fishing gear",
        "observed_at": datetime(2026, 9, the_day, 8, 0, tzinfo=timezone.utc),
        "submitted_at": datetime(2026, 9, the_day, 20, 0, tzinfo=timezone.utc),
        "assessment_state": the_state,
    }


def make_follow_up(
    the_type: str = "monitoring",
    the_owned: bool = True,
    the_day: int = 15,
) -> dict:
    return {
        "report_reference": "RC-0001",
        "owned_by_you": the_owned,
        "follow_up_type": the_type,
        "follow_up_state": (
            "monitoring_recorded" if the_type == "monitoring" else "action_taken"
        ),
        "action_date": date(2026, 9, the_day),
        "responsible_team": "Reef team",
        "recorded_outcome": None,
        "condition_code": "improving" if the_type == "monitoring" else None,
        "condition_label": "Improving" if the_type == "monitoring" else None,
        "next_follow_up_required": False,
        "next_follow_up_date": None,
        "created_at": datetime(2026, 9, the_day, 18, 0, tzinfo=timezone.utc),
    }


def patch_repository(monkeypatch, the_observations, the_follow_ups):
    monkeypatch.setattr(
        the_service.the_repository, "get_site_identity",
        AsyncMock(return_value={
            "dive_site_id": 1,
            "site_name": "Tiger Reef",
            "public_area_label": "Tioman Island",
        }),
    )
    monkeypatch.setattr(
        the_service.the_repository, "list_site_observations",
        AsyncMock(return_value=the_observations),
    )
    monkeypatch.setattr(
        the_service.the_repository, "list_site_follow_ups",
        AsyncMock(return_value=the_follow_ups),
    )


# ---------------------------------------------------------------------------
# AC3 — assessment states stay distinct
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "the_stored_state, the_expected",
    [
        ("not_yet_assessed", AssessmentState.NOT_YET_ASSESSED),
        ("under_review", AssessmentState.UNDER_REVIEW),
        ("evidence_accepted", AssessmentState.EVIDENCE_ACCEPTED),
        ("not_substantiated", AssessmentState.NOT_SUBSTANTIATED),
        ("closed_without_assessment", AssessmentState.CLOSED_WITHOUT_ASSESSMENT),
    ],
)
def test_each_assessment_state_carries_its_own_label(the_stored_state, the_expected):
    the_item = the_service.to_observation_item(make_observation(the_stored_state))

    assert the_item.assessment_state == the_expected
    assert the_item.assessment_state_label

    # an unreviewed observation must never read like an accepted one
    if the_expected != AssessmentState.EVIDENCE_ACCEPTED:
        assert "accepted" not in the_item.assessment_state_label.lower()


# ---------------------------------------------------------------------------
# AC4 — record types are not flattened
# ---------------------------------------------------------------------------

def test_record_types_are_distinct():
    assert (
        the_service.to_observation_item(make_observation()).record_type
        == SiteHistoryRecordType.OBSERVATION
    )

    assert (
        the_service.to_follow_up_item(make_follow_up("monitoring")).record_type
        == SiteHistoryRecordType.MONITORING
    )

    assert (
        the_service.to_follow_up_item(make_follow_up("action")).record_type
        == SiteHistoryRecordType.ACTION
    )

    assert (
        the_service.to_follow_up_item(make_follow_up("sourced_outcome")).record_type
        == SiteHistoryRecordType.SOURCED_OUTCOME
    )


def test_a_monitoring_record_keeps_its_condition():
    the_item = the_service.to_follow_up_item(make_follow_up("monitoring"))

    assert the_item.condition_code == "improving"
    assert the_item.condition_label == "Improving"


# ---------------------------------------------------------------------------
# US1.3 AC2 — another Coordinator's report reference stays hidden
# ---------------------------------------------------------------------------

def test_report_reference_hidden_for_a_case_you_do_not_own():
    the_item = the_service.to_observation_item(
        make_observation(the_owned=False, the_reference="RC-0099")
    )

    assert the_item.report_reference is None
    assert the_item.owned_by_you is False

    # the entry itself still appears, with its category and state
    assert the_item.threat_category_code == "ghost_gear"
    assert the_item.assessment_state is not None


def test_report_reference_shown_for_your_own_case():
    the_item = the_service.to_observation_item(
        make_observation(the_owned=True, the_reference="RC-0001")
    )

    assert the_item.report_reference == "RC-0001"
    assert the_item.owned_by_you is True


# ---------------------------------------------------------------------------
# AC5 — too little history says so
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_site_reports_insufficient_history(monkeypatch):
    patch_repository(monkeypatch, [], [])

    the_response = await the_service.get_site_history(AsyncMock(), 1, 42)

    assert the_response.state == SiteHistoryState.INSUFFICIENT_HISTORY
    assert the_response.items == []

    the_message = the_response.message.lower()
    assert "not enough" in the_message

    # never a claim about the reef itself
    for the_phrase in ("healthy", "no threats", "safe", "clear"):
        assert the_phrase not in the_message


@pytest.mark.asyncio
async def test_a_single_record_is_not_a_history(monkeypatch):
    patch_repository(monkeypatch, [make_observation()], [])

    the_response = await the_service.get_site_history(AsyncMock(), 1, 42)

    assert the_response.state == SiteHistoryState.INSUFFICIENT_HISTORY
    assert the_response.items == []

    # the count is still reported honestly
    assert the_response.counts.observations == 1


# ---------------------------------------------------------------------------
# AC4 / AC6 — chronological, counted, and separate from hotspot analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_is_chronological_and_counted(monkeypatch):
    patch_repository(
        monkeypatch,
        [
            make_observation(the_day=20, the_state="under_review"),
            make_observation(the_day=2, the_state="evidence_accepted"),
        ],
        [make_follow_up("monitoring", the_day=10)],
    )

    the_response = await the_service.get_site_history(AsyncMock(), 1, 42)

    assert the_response.state == SiteHistoryState.AVAILABLE

    the_days = [
        the_item.occurred_on or the_item.recorded_at.date()
        for the_item in the_response.items
    ]
    assert the_days == sorted(the_days)

    assert the_response.counts.observations == 2
    assert the_response.counts.monitoring_visits == 1
    assert the_response.counts.observations_by_assessment_state == {
        "under_review": 1,
        "evidence_accepted": 1,
    }

    assert the_response.first_record_on == date(2026, 9, 2)
    assert the_response.last_record_on == date(2026, 9, 20)

    # AC6: the response points at E5 for broader patterns
    assert "hotspot" in the_response.hotspot_note.lower()


@pytest.mark.asyncio
async def test_unknown_site_is_not_found(monkeypatch):
    monkeypatch.setattr(
        the_service.the_repository, "get_site_identity", AsyncMock(return_value=None)
    )

    with pytest.raises(NotFoundError):
        await the_service.get_site_history(AsyncMock(), 999, 42)


@pytest.mark.asyncio
async def test_no_private_report_content_is_returned(monkeypatch):
    patch_repository(
        monkeypatch,
        [make_observation(the_day=1), make_observation(the_day=3, the_owned=False)],
        [make_follow_up("monitoring", the_day=5)],
    )

    the_response = await the_service.get_site_history(AsyncMock(), 1, 42)

    the_payload = str(the_response.model_dump(by_alias=True)).lower()

    for the_forbidden in ("description", "latitude", "longitude", "observer", "notes"):
        assert the_forbidden not in the_payload


# ---------------------------------------------------------------------------
# QA-E8-01 — a closed case is never shown as accepted
# ---------------------------------------------------------------------------

def test_a_closed_case_shows_its_closed_label_not_accepted():
    the_row = make_observation("closed")
    the_row["case_status_label"] = "Closed — No Action Required"

    the_item = the_service.to_observation_item(the_row)

    assert the_item.assessment_state == AssessmentState.CLOSED
    assert the_item.assessment_state_label == "Closed — No Action Required"
    assert "accepted" not in the_item.assessment_state_label.lower()


def test_a_closed_case_without_a_status_label_falls_back_to_closed():
    the_item = the_service.to_observation_item(make_observation("closed"))

    assert the_item.assessment_state_label == "Closed"
