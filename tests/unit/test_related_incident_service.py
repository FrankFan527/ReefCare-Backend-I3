# ---------------------------------------------------------------------------
# US5.9 Related Incidents — unit tests (no database).
#
# Covers the rules that live in Python: analysis-state mapping (AC3/AC9),
# the AC4 ownership filter, decision state and the AC7 reopen rule, request
# validation, SQLSTATE mapping, and the engine wrapper never raising.
# ---------------------------------------------------------------------------

import asyncio
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
async def test_engine_exception_marks_run_failed(monkeypatch):
    the_repo = the_engine.the_repository
    monkeypatch.setattr(the_engine.image_embedding_repository, "list_image_inputs", AsyncMock(return_value=[]))
    monkeypatch.setattr(the_repo, "get_latest_detection_run", AsyncMock(return_value=None))

    monkeypatch.setattr(the_repo, "get_report_comparison_facts", AsyncMock(return_value={
        "report_id": 1, "report_reference": "RC-0001",
        "observed_at": THE_NOW, "threat_category_code": "ghost_gear",
    }))
    monkeypatch.setattr(the_repo, "begin_detection_run", AsyncMock(return_value=7))
    monkeypatch.setattr(the_repo, "list_candidate_comparison_facts", AsyncMock(return_value=[]))
    monkeypatch.setattr(the_engine, "match_related_reports", AsyncMock(side_effect=RuntimeError("test failure")))

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


@pytest.mark.asyncio
async def test_comparison_does_not_load_private_details_if_candidate_not_owned(monkeypatch):
    owner_check = AsyncMock(side_effect=[{}, AuthorizationError("not yours")])
    private_read = AsyncMock()
    monkeypatch.setattr(the_service, "load_owned_case", owner_check)
    monkeypatch.setattr(the_service.the_repository, "get_comparison_side", private_read)
    with pytest.raises(AuthorizationError):
        await the_service.compare_reports(AsyncMock(), "RC-0001", "RC-0002", 42)
    assert owner_check.await_count == 2
    private_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_race_never_opens_comparison(monkeypatch):
    from app.core.exceptions import ConflictError
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(the_service.the_repository, "get_report_identity", AsyncMock(side_effect=[
        {"report_id": 1}, {"report_id": 2, "claimed_by_user_id": None},
    ]))
    monkeypatch.setattr(the_service.the_repository, "find_candidate_in_latest_run", AsyncMock(return_value={"rule_version": "rid-v1"}))
    monkeypatch.setattr(the_service, "claim_report_service", AsyncMock(side_effect=ConflictError("claimed already")))
    compare = AsyncMock()
    monkeypatch.setattr(the_service, "compare_reports", compare)
    with pytest.raises(ConflictError):
        await the_service.claim_and_compare(AsyncMock(), "RC-0001", "RC-0002", 42)
    compare.assert_not_awaited()


@pytest.mark.asyncio
async def test_comparison_passes_authenticated_owner_to_protected_queries(monkeypatch):
    monkeypatch.setattr(the_service,"load_owned_case",AsyncMock(return_value={}))
    private_read = AsyncMock(return_value=None)
    monkeypatch.setattr(the_service.the_repository,"get_comparison_side",private_read)
    with pytest.raises(NotFoundError):
        await the_service.compare_reports(AsyncMock(),"RC-0001","RC-0002",42)
    assert private_read.await_count == 2
    assert all(call.kwargs["coordinator_id"] == 42 for call in private_read.await_args_list)


@pytest.mark.asyncio
async def test_analysis_read_timeout_stays_unavailable_even_if_rollback_fails(monkeypatch):
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    monkeypatch.setattr(the_service, "_build_related_reports", AsyncMock(side_effect=TimeoutError()))
    db = AsyncMock()
    db.rollback.side_effect = RuntimeError("connection gone")
    response = await the_service.get_related_reports(db, "RC-0001", 42)
    assert response.analysis_state == RelatedAnalysisState.UNAVAILABLE
    assert response.candidates == []


def mock_decision_dependencies(monkeypatch, first_incident, second_incident):
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(return_value={}))
    identities = [
        {"report_id": 1, "report_reference": "RC-0001", "claimed_by_user_id": 42, "incident_id": first_incident},
        {"report_id": 2, "report_reference": "RC-0002", "claimed_by_user_id": 42, "incident_id": second_incident},
    ]
    monkeypatch.setattr(the_service.the_repository, "get_report_identity", AsyncMock(side_effect=[
        *identities,
    ]))
    monkeypatch.setattr(the_service.the_repository, "lock_relationship_reports", AsyncMock(
        return_value={row["report_reference"]: row for row in identities}))
    suggestion = AsyncMock(return_value={"rule_version": "rid-v2-image"})
    monkeypatch.setattr(the_service, "_find_suggestion_either_direction", suggestion)
    saved = {"out_incident_reference": f"INC-{first_incident or second_incident or 30}",
             "out_decided_at": THE_NOW}
    confirm = AsyncMock(return_value=saved)
    reject = AsyncMock(return_value={"out_decided_at": THE_NOW})
    monkeypatch.setattr(the_service.the_repository, "confirm_same_incident", confirm)
    monkeypatch.setattr(the_service.the_repository, "record_not_related", reject)
    return suggestion, confirm, reject


@pytest.mark.parametrize("first_incident,second_incident", [
    (None, None), (10, None), (None, 10), (10, 10), (10, 20), (20, 10),
])
@pytest.mark.asyncio
async def test_confirmation_incident_membership_policy(monkeypatch, first_incident, second_incident):
    suggestion, confirm, reject = mock_decision_dependencies(monkeypatch, first_incident, second_incident)
    db = AsyncMock()
    request = RelationshipDecisionCreate(decision="same_incident", note="  Verified reef observation.  ")
    if first_incident is not None and second_incident is not None and first_incident != second_incident:
        with pytest.raises(WorkflowError, match="Combining incident groups is outside this workflow"):
            await the_service.record_relationship_decision(db, "RC-0001", "RC-0002", 42, request)
        confirm.assert_not_awaited()
        suggestion.assert_not_awaited()
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
    else:
        response = await the_service.record_relationship_decision(db, "RC-0001", "RC-0002", 42, request)
        assert response.incident_reference == f"INC-{first_incident or second_incident or 30}"
        assert response.decided_by == 42
        confirm.assert_awaited_once()
        assert confirm.await_args.kwargs["note"] == "Verified reef observation."
        assert confirm.await_args.kwargs["suggested_rule_version"] == "rid-v2-image"
        db.commit.assert_awaited_once()
    reject.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_function_conflict_is_rolled_back(monkeypatch):
    _, confirm, _ = mock_decision_dependencies(monkeypatch, None, None)
    confirm.side_effect = make_dbapi_error("RC409", the_service.INCIDENT_GROUP_MERGE_BLOCKED_MESSAGE)
    db = AsyncMock()
    with pytest.raises(WorkflowError, match="different incidents"):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_incidents_can_still_be_marked_not_related(monkeypatch):
    _, confirm, reject = mock_decision_dependencies(monkeypatch, 10, 20)
    db = AsyncMock()
    response = await the_service.record_relationship_decision(
        db, "RC-0001", "RC-0002", 42,
        RelationshipDecisionCreate(decision="not_related", rejection_reason_code="different_object"))
    assert response.decision == "not_related"
    assert response.incident_reference is None
    confirm.assert_not_awaited()
    reject.assert_awaited_once()
    db.commit.assert_awaited_once()
    the_service.the_repository.lock_relationship_reports.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_uses_membership_after_waiting_for_lock(monkeypatch):
    suggestion, confirm, _ = mock_decision_dependencies(monkeypatch, None, None)
    order = []

    async def checked_owner(**kwargs):
        order.append("ownership")
        return {"incident_id": None}

    async def locked_reports(**kwargs):
        # A different confirmation completed before we acquired the lock.
        order.append("locked_memberships")
        return {
            "RC-0001": {"report_id": 1, "claimed_by_user_id": 42, "incident_id": 10},
            "RC-0002": {"report_id": 2, "claimed_by_user_id": 42, "incident_id": 20},
        }

    monkeypatch.setattr(the_service, "load_owned_case", checked_owner)
    monkeypatch.setattr(the_service.the_repository, "lock_relationship_reports", locked_reports)
    db = AsyncMock()
    with pytest.raises(WorkflowError):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    assert order == ["ownership", "ownership", "locked_memberships"]
    the_service.the_repository.get_report_identity.assert_not_awaited()
    confirm.assert_not_awaited()
    suggestion.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize("owner", [None, 99])
@pytest.mark.asyncio
async def test_ownership_change_while_waiting_does_not_disclose_incidents(monkeypatch, owner):
    suggestion, confirm, _ = mock_decision_dependencies(monkeypatch, 10, 20)
    the_service.the_repository.lock_relationship_reports.return_value["RC-0002"]["claimed_by_user_id"] = owner
    db = AsyncMock()
    with pytest.raises(AuthorizationError, match="Both reports must be owned by you"):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    confirm.assert_not_awaited()
    suggestion.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_removed_while_waiting_releases_locks(monkeypatch):
    _, confirm, _ = mock_decision_dependencies(monkeypatch, None, None)
    del the_service.the_repository.lock_relationship_reports.return_value["RC-0002"]
    db = AsyncMock()
    with pytest.raises(NotFoundError):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    confirm.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.parametrize("failure", [
    make_dbapi_error("42501", "private permission detail"), asyncio.CancelledError(),
])
@pytest.mark.asyncio
async def test_lock_failure_or_cancellation_rolls_back(monkeypatch, failure):
    _, confirm, _ = mock_decision_dependencies(monkeypatch, None, None)
    the_service.the_repository.lock_relationship_reports.side_effect = failure
    db = AsyncMock()
    expected = asyncio.CancelledError if isinstance(failure, asyncio.CancelledError) else DatabaseOperationError
    with pytest.raises(expected):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    confirm.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorised_confirmation_never_acquires_locks(monkeypatch):
    _, confirm, _ = mock_decision_dependencies(monkeypatch, None, None)
    monkeypatch.setattr(the_service, "load_owned_case", AsyncMock(side_effect=AuthorizationError()))
    db = AsyncMock()
    with pytest.raises(AuthorizationError):
        await the_service.record_relationship_decision(
            db, "RC-0001", "RC-0002", 42, RelationshipDecisionCreate(decision="same_incident"))
    the_service.the_repository.lock_relationship_reports.assert_not_awaited()
    confirm.assert_not_awaited()
    db.rollback.assert_awaited_once()
