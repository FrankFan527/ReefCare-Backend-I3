import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import require_authentication
from app.api.dependencies.authorization import require_coordinator, require_observer
from app.api.routes import reports
from app.core.exceptions import AuthorizationError, ConflictError
from app.db.session import get_db_session
from app.main import app
from app.schemas.related_incident import RelatedReportsResponse, RelatedAnalysisState, RelationshipDecisionResponse, ImageAnalysisState
from app.services import related_incident_service as service
from app.services.report_service import ReportValidationError

BASE = "/api/v1/coordinator/reports/RC-0001/related-reports"
NOW = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)


@pytest.fixture
def client():
    app.dependency_overrides.clear()
    async def fake_db():
        yield AsyncMock()
    app.dependency_overrides[get_db_session] = fake_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def authorise_coordinator():
    app.dependency_overrides[require_coordinator] = lambda: {"user_id": 42, "role": "case_coordinator"}


@pytest.mark.parametrize("method,path,body", [
    ("get", BASE, None), ("get", BASE + "/RC-0002/compare", None),
    ("post", BASE + "/RC-0002/claim-and-compare", None),
    ("post", BASE + "/RC-0002/decision", {"decision": "same_incident"}),
    ("get", "/api/v1/coordinator/related-reports/rejection-reasons", None),
])
def test_related_incident_endpoints_require_login(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("role", ["observer", "system_administrator"])
def test_observers_and_administrators_cannot_use_related_reports(client, role):
    app.dependency_overrides[require_authentication] = lambda: {"user_id": 3, "role": role}
    assert client.get(BASE).status_code == 403


@pytest.mark.parametrize("state", list(RelatedAnalysisState))
def test_analysis_states_have_an_explicit_frontend_contract(client, monkeypatch, state):
    authorise_coordinator()
    mock = AsyncMock(return_value=RelatedReportsResponse(
        report_reference="RC-0001", analysis_state=state, message=service.THE_ANALYSIS_MESSAGES[state]))
    monkeypatch.setattr(service, "get_related_reports", mock)
    response = client.get(BASE)
    assert response.status_code == 200
    assert response.json()["analysisState"] == state.value
    assert response.json()["candidates"] == []
    mock.assert_awaited_once()
    assert mock.await_args.kwargs["coordinator_id"] == 42


def test_current_report_ownership_error_is_not_hidden_as_unavailable(client, monkeypatch):
    authorise_coordinator()
    monkeypatch.setattr(service, "get_related_reports", AsyncMock(side_effect=AuthorizationError("not yours")))
    assert client.get(BASE).status_code == 403


@pytest.mark.parametrize("state",list(ImageAnalysisState))
def test_photo_availability_is_independent_of_completed_text_analysis(client,monkeypatch,state):
    authorise_coordinator()
    response_model = RelatedReportsResponse(
        report_reference="RC-0001",analysis_state="matches_available",message="Available for review.",
        rule_version="rid-v2-image",input_version=2,image_analysis_state=state,
        image_analysis_message=service.IMAGE_ANALYSIS_MESSAGES[state],
        candidates=[{"candidate_report_reference":"RC-0002","relatedness_level":"high","relatedness_score":.9695,
                     "ownership_state":"unclaimed","decision_state":"undecided",
                     "signals":[{"code":"similar_image","label":"Similar image evidence","signal_score":.93,"signal_weight":.15}]}])
    monkeypatch.setattr(service,"get_related_reports",AsyncMock(return_value=response_model))
    payload = client.get(BASE).json()
    assert payload["imageAnalysisState"] == state.value and payload["inputVersion"] == 2
    signal = payload["candidates"][0]["signals"][0]
    assert signal["signalScore"] == .93 and signal["signalWeight"] == .15
    assert payload["candidates"][0]["relatednessScore"] == .9695
    assert "imageEmbedding" not in str(payload) and "fileReference" not in str(payload)


def test_claim_race_returns_409_without_private_details(client, monkeypatch):
    authorise_coordinator()
    monkeypatch.setattr(service, "claim_and_compare", AsyncMock(side_effect=ConflictError("Another Coordinator claimed this report first")))
    response = client.post(BASE + "/RC-0002/claim-and-compare")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert "description" not in response.json()


def test_explicit_decision_uses_authenticated_actor(client, monkeypatch):
    authorise_coordinator()
    mock = AsyncMock(return_value=RelationshipDecisionResponse(
        report_reference="RC-0001", related_report_reference="RC-0002", decision="same_incident",
        incident_reference="INC-1", decided_by=42, decided_at=NOW))
    monkeypatch.setattr(service, "record_relationship_decision", mock)
    response = client.post(BASE + "/RC-0002/decision", json={"decision": "same_incident"})
    assert response.status_code == 201
    assert response.json()["incidentReference"] == "INC-1"
    assert mock.await_args.kwargs["coordinator_id"] == 42


def test_not_related_requires_reason_before_service_is_called(client, monkeypatch):
    authorise_coordinator()
    mock = AsyncMock()
    monkeypatch.setattr(service, "record_relationship_decision", mock)
    assert client.post(BASE + "/RC-0002/decision", json={"decision": "not_related"}).status_code == 422
    mock.assert_not_awaited()


PAYLOAD = {
    "threatCategoryId": 1, "observedAt": "2026-08-29T05:00:00Z",
    "description": "Fishing net tangled around a branching coral.", "diveSessionId": 1,
    "location": {"namedDiveSiteId": 1, "locationConfidence": "dive_site_only", "locationSource": "named_dive_site"},
}


def test_successful_submission_schedules_detection_after_commit(client, monkeypatch):
    app.dependency_overrides[require_observer] = lambda: {"user_id": 3, "role": "observer"}
    order = []
    async def submitted(**kwargs):
        order.append("committed submission")
        return {"report_reference": "RC-0001", "status": "received", "submitted_at": NOW, "general_location": "Tioman"}
    async def background(reference):
        assert reference == "RC-0001"
        order.append("background detection")
    monkeypatch.setattr(reports, "submit_report_service", submitted)
    monkeypatch.setattr(reports, "run_related_incident_detection_in_background", background)
    response = client.post("/api/v1/reports", data={"payload": json.dumps(PAYLOAD)},
                           files={"photos": ("reef.jpg", b"photo", "image/jpeg")})
    assert response.status_code == 201
    assert response.json()["reportReference"] == "RC-0001"
    assert order == ["committed submission", "background detection"]


def test_failed_submission_never_schedules_detection(client, monkeypatch):
    app.dependency_overrides[require_observer] = lambda: {"user_id": 3, "role": "observer"}
    monkeypatch.setattr(reports, "submit_report_service", AsyncMock(side_effect=ReportValidationError("invalid session")))
    background = AsyncMock()
    monkeypatch.setattr(reports, "run_related_incident_detection_in_background", background)
    response = client.post("/api/v1/reports", data={"payload": json.dumps(PAYLOAD)},
                           files={"photos": ("reef.jpg", b"photo", "image/jpeg")})
    assert response.status_code == 400
    background.assert_not_awaited()
