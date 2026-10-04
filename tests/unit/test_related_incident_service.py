# ---------------------------------------------------------------------------
# US5.9 Related Incidents — unit tests (no database).
#
# Covers the rules that live in Python: analysis-state mapping (AC3/AC9),
# the AC4 ownership filter, decision state and the AC7 reopen rule, request
# validation, SQLSTATE mapping, and the engine wrapper never raising.
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import (
    AuthorizationError,
    DatabaseOperationError,
    DomainValidationError,
    NotFoundError,
    WorkflowError,
)
from app.schemas.related_incident import (
    CandidateDecisionState,
    CandidateOwnershipState,
    DetectionRunState,
    RelatedAnalysisState,
    RelationshipDecisionCreate,
)
from app.services import related_incident_detection_service as the_engine
from app.services import related_incident_service as the_service


THE_NOW = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def make_run(the_state: str, the_minutes_ago: int = 1) -> dict:
    return {
        "related_incident_run_id": 7,
        "rule_version": "rid-v1",
        "run_state": the_state,
        "started_at": THE_NOW - timedelta(minutes=the_minutes_ago),
        "finished_at": None if the_state == "processing" else THE_NOW,
    }


# ---------------------------------------------------------------------------
# AC3 / AC9 — analysis state
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "the_run, the_count, the_expected",
    [
        (None, 0, RelatedAnalysisState.UNAVAILABLE),
        (make_run("processing", 1), 0, RelatedAnalysisState.PROCESSING),
        (make_run("processing", 30), 0, RelatedAnalysisState.UNAVAILABLE),
        (make_run("failed"), 0, RelatedAnalysisState.UNAVAILABLE),
        (make_run("insufficient_information"), 0, RelatedAnalysisState.INSUFFICIENT_INFORMATION),
        (make_run("completed"), 2, RelatedAnalysisState.MATCHES_AVAILABLE),
        (make_run("completed"), 0, RelatedAnalysisState.NO_AVAILABLE_MATCHES),
    ],
)
def test_analysis_state_mapping(the_run, the_count, the_expected):
    assert the_service.derive_analysis_state(the_run, the_count, THE_NOW) == the_expected


def test_failure_is_never_reported_as_no_matches():
    # AC9: a failed run with nothing stored must not read as "no related reports"
    the_state = the_service.derive_analysis_state(make_run("failed"), 0, THE_NOW)

    assert the_state != RelatedAnalysisState.NO_AVAILABLE_MATCHES
    assert "unavailable" in the_service.THE_ANALYSIS_MESSAGES[the_state].lower()


# ---------------------------------------------------------------------------
# AC4 — only Unclaimed or Owned by you
# ---------------------------------------------------------------------------

def test_ownership_filter():
    assert the_service.derive_ownership_state(None, 42) == CandidateOwnershipState.UNCLAIMED
    assert the_service.derive_ownership_state(42, 42) == CandidateOwnershipState.OWNED_BY_YOU
    assert the_service.derive_ownership_state(99, 42) is None


# ---------------------------------------------------------------------------
# AC6 / AC7 — decision state and the new-evidence reopen rule
# ---------------------------------------------------------------------------

def test_shared_incident_reads_as_linked_without_a_pair_decision():
    the_state, the_reopened = the_service.derive_decision_state(5, 5, None, None)

    assert the_state == CandidateDecisionState.LINKED
    assert the_reopened is False


def test_not_related_stays_decided_without_new_evidence():
    the_decision = {"decision": "not_related", "decided_at": THE_NOW}
    the_older_evidence = THE_NOW - timedelta(days=1)

    the_state, the_reopened = the_service.derive_decision_state(
        None, None, the_decision, the_older_evidence
    )

    assert the_state == CandidateDecisionState.NOT_RELATED
    assert the_reopened is False


def test_not_related_reopens_when_evidence_arrives_later():
    the_decision = {"decision": "not_related", "decided_at": THE_NOW}
    the_newer_evidence = THE_NOW + timedelta(hours=2)

    the_state, the_reopened = the_service.derive_decision_state(
        None, None, the_decision, the_newer_evidence
    )

    assert the_state == CandidateDecisionState.UNDECIDED
    assert the_reopened is True


def test_no_decision_is_undecided():
    the_state, _ = the_service.derive_decision_state(None, None, None, None)

    assert the_state == CandidateDecisionState.UNDECIDED


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_not_related_requires_a_reason():
    with pytest.raises(ValidationError):
        RelationshipDecisionCreate(decision="not_related")


def test_same_incident_rejects_a_reason():
    with pytest.raises(ValidationError):
        RelationshipDecisionCreate(
            decision="same_incident",
            rejection_reason_code="different_object",
        )


def test_camel_case_request_is_accepted():
    the_request = RelationshipDecisionCreate.model_validate(
        {"decision": "not_related", "rejectionReasonCode": "different_time"}
    )

    assert the_request.rejection_reason_code == "different_time"


# ---------------------------------------------------------------------------
# PostgreSQL RC4xx -> ServiceError
# ---------------------------------------------------------------------------

def make_dbapi_error(the_sqlstate: str, the_message: str) -> DBAPIError:
    the_orig = SimpleNamespace(
        sqlstate=the_sqlstate,
        diag=SimpleNamespace(message_primary=the_message),
    )

    return DBAPIError("statement", {}, the_orig)


@pytest.mark.parametrize(
    "the_sqlstate, the_expected_error",
    [
        ("RC400", DomainValidationError),
        ("RC403", AuthorizationError),
        ("RC404", NotFoundError),
        ("RC409", WorkflowError),
        ("23505", DatabaseOperationError),
    ],
)
def test_sqlstate_mapping(the_sqlstate, the_expected_error):
    with pytest.raises(the_expected_error):
        the_service.raise_mapped_database_error(
            make_dbapi_error(the_sqlstate, "message from the function")
        )


def test_unmapped_database_errors_hide_the_detail():
    with pytest.raises(DatabaseOperationError) as the_raised:
        the_service.raise_mapped_database_error(
            make_dbapi_error("XX000", "internal detail that must not leak")
        )

    assert "internal detail" not in the_raised.value.message


# ---------------------------------------------------------------------------
# Ownership is checked before anything about candidates is read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_related_reports_require_ownership_first(monkeypatch):
    the_owner_check = AsyncMock(side_effect=AuthorizationError("not yours"))
    the_identity_read = AsyncMock()

    monkeypatch.setattr(the_service, "load_owned_case", the_owner_check)
    monkeypatch.setattr(the_service.the_repository, "get_report_identity", the_identity_read)

    with pytest.raises(AuthorizationError):
        await the_service.get_related_reports(AsyncMock(), "RC-0001", 42)

    the_identity_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidates_owned_by_others_are_removed(monkeypatch):
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(the_service, "utc_now", lambda: THE_NOW)

    the_repo = the_service.the_repository

    monkeypatch.setattr(the_repo, "get_report_identity", AsyncMock(return_value={
        "report_id": 1, "report_reference": "RC-0001",
        "claimed_by_user_id": 42, "incident_id": None,
    }))
    monkeypatch.setattr(the_repo, "get_latest_detection_run", AsyncMock(return_value=make_run("completed")))
    monkeypatch.setattr(the_repo, "list_run_candidates", AsyncMock(return_value=[
        {"related_incident_candidate_id": 10, "candidate_report_id": 2,
         "candidate_report_reference": "RC-0002", "candidate_claimed_by_user_id": None,
         "candidate_incident_id": None, "relatedness_level": "high", "similarity_score": None},
        {"related_incident_candidate_id": 11, "candidate_report_id": 3,
         "candidate_report_reference": "RC-0003", "candidate_claimed_by_user_id": 99,
         "candidate_incident_id": None, "relatedness_level": "high", "similarity_score": None},
    ]))
    monkeypatch.setattr(the_repo, "list_run_candidate_signals", AsyncMock(return_value=[
        {"related_incident_candidate_id": 10, "code": "same_dive_site",
         "label": "Same named dive site", "detail": None},
    ]))
    monkeypatch.setattr(the_repo, "list_latest_pair_decisions", AsyncMock(return_value=[]))
    monkeypatch.setattr(the_repo, "get_latest_evidence_times", AsyncMock(return_value={}))

    the_response = await the_service.get_related_reports(AsyncMock(), "RC-0001", 42)

    assert the_response.analysis_state == RelatedAnalysisState.MATCHES_AVAILABLE
    assert [c.candidate_report_reference for c in the_response.candidates] == ["RC-0002"]
    assert the_response.candidates[0].ownership_state == CandidateOwnershipState.UNCLAIMED
    assert the_response.candidates[0].signals[0].label == "Same named dive site"

    # AC3: the serialised candidate carries no private report content
    the_payload = the_response.model_dump(by_alias=True)
    assert "description" not in str(the_payload).lower()


@pytest.mark.asyncio
async def test_read_failure_degrades_to_unavailable(monkeypatch):
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(
        the_service.the_repository,
        "get_report_identity",
        AsyncMock(side_effect=OperationalError("stmt", {}, Exception("down"))),
    )

    the_response = await the_service.get_related_reports(AsyncMock(), "RC-0001", 42)

    assert the_response.analysis_state == RelatedAnalysisState.UNAVAILABLE
    assert the_response.candidates == []


# ---------------------------------------------------------------------------
# Engine wrapper: never raises, marks the run failed (AC1, AC9)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unimplemented_engine_marks_run_failed(monkeypatch):
    the_repo = the_engine.the_repository

    monkeypatch.setattr(the_repo, "get_report_comparison_facts", AsyncMock(return_value={
        "report_id": 1, "report_reference": "RC-0001",
        "observed_at": THE_NOW, "threat_category_code": "ghost_gear",
    }))
    monkeypatch.setattr(the_repo, "begin_detection_run", AsyncMock(return_value=7))
    monkeypatch.setattr(the_repo, "list_candidate_comparison_facts", AsyncMock(return_value=[]))

    the_finish = AsyncMock()
    monkeypatch.setattr(the_repo, "finish_detection_run", the_finish)

    the_result = await the_engine.run_related_incident_detection(AsyncMock(), "RC-0001")

    assert the_result == DetectionRunState.FAILED
    assert the_finish.await_args.kwargs["run_state"] == DetectionRunState.FAILED


@pytest.mark.asyncio
async def test_ineligible_report_is_skipped_without_a_run(monkeypatch):
    the_repo = the_engine.the_repository

    monkeypatch.setattr(the_repo, "get_report_comparison_facts", AsyncMock(return_value=None))

    the_begin = AsyncMock()
    monkeypatch.setattr(the_repo, "begin_detection_run", the_begin)

    the_result = await the_engine.run_related_incident_detection(AsyncMock(), "RC-9999")

    assert the_result is None
    the_begin.assert_not_awaited()
