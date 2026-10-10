# ---------------------------------------------------------------------------
# QA (Rifdhan, 10 Oct) — follow-up photo upload route.
#
# The frontend sent caseEventId 593 to the Iteration 2 /actions/{id}/evidence
# route, which looks up a caseActionId, so every follow-up photo came back
# 404. These tests pin the follow-up route that replaces it for Iteration 3
# records: keyed by caseActionId, multipart field `file`, 201 with safe
# metadata, and the same 400/413 file errors as every other photo upload.
# ---------------------------------------------------------------------------

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import require_coordinator
from app.api.routes import follow_ups as follow_up_routes
from app.core.exceptions import NotFoundError
from app.db.session import get_db_session
from app.main import app
from app.schemas.follow_up import FollowUpEvidenceUploaded
from app.services.evidence_service import (
    EvidenceTooLargeError,
    EvidenceValidationError,
)


THE_UPLOAD_PATH: str = "/api/v1/coordinator/reports/RC-0092/follow-ups/30/evidence"


async def override_db_session():
    yield object()


def override_coordinator():
    return {"user_id": 12, "role": "case_coordinator"}


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def the_client():
    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[require_coordinator] = override_coordinator

    with TestClient(app) as the_test_client:
        yield the_test_client


def send_photo(the_client: TestClient, the_path: str = THE_UPLOAD_PATH):
    return the_client.post(
        the_path,
        files={"file": ("cleanup.jpg", b"\xff\xd8\xff-photo-bytes", "image/jpeg")},
    )


def test_follow_up_photo_is_uploaded_by_case_action_id(the_client, monkeypatch):
    the_service_mock = AsyncMock(
        return_value=FollowUpEvidenceUploaded(
            evidence_id=501,
            media_type="photo",
            file_size_bytes=2048,
            uploaded_at=datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc),
            case_action_id=30,
            case_event_id=593,
        )
    )
    monkeypatch.setattr(
        follow_up_routes.follow_up_service, "attach_follow_up_evidence", the_service_mock
    )

    the_response = send_photo(the_client)

    assert the_response.status_code == 201
    assert the_response.json() == {
        "evidenceId": 501,
        "mediaType": "photo",
        "fileSizeBytes": 2048,
        "uploadedAt": "2026-10-10T03:00:00Z",
        "caseActionId": 30,
        "caseEventId": 593,
    }

    the_kwargs = the_service_mock.await_args.kwargs
    assert the_kwargs["report_reference"] == "RC-0092"
    assert the_kwargs["case_action_id"] == 30
    assert the_kwargs["coordinator_id"] == 12


def test_unknown_follow_up_is_a_clean_404(the_client, monkeypatch):
    monkeypatch.setattr(
        follow_up_routes.follow_up_service, "attach_follow_up_evidence",
        AsyncMock(side_effect=NotFoundError("Follow-up 593 was not found on report RC-0092")),
    )

    the_response = send_photo(
        the_client, "/api/v1/coordinator/reports/RC-0092/follow-ups/593/evidence"
    )

    assert the_response.status_code == 404
    assert "593" in the_response.json()["detail"]


@pytest.mark.parametrize(
    ("the_error", "the_expected_status"),
    [
        (EvidenceValidationError("Unsupported photo type. Allowed types are JPEG, PNG and WebP."), 400),
        (EvidenceTooLargeError("Photo exceeds the maximum allowed size of 10 MB"), 413),
    ],
)
def test_bad_files_get_the_shared_photo_errors(
    the_client, monkeypatch, the_error, the_expected_status
):
    monkeypatch.setattr(
        follow_up_routes.follow_up_service, "attach_follow_up_evidence",
        AsyncMock(side_effect=the_error),
    )

    the_response = send_photo(the_client)

    assert the_response.status_code == the_expected_status
    assert the_response.json()["detail"] == str(the_error)


def test_the_file_field_is_required(the_client):
    the_response = the_client.post(THE_UPLOAD_PATH, files={})

    assert the_response.status_code == 422


def test_an_observer_cannot_upload_follow_up_photos():
    # no coordinator override: the real role dependency rejects the request
    app.dependency_overrides[get_db_session] = override_db_session

    with TestClient(app) as the_test_client:
        the_response = send_photo(the_test_client)

    assert the_response.status_code in (401, 403)
