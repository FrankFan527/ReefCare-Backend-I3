from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import (
    require_authentication,
)
from app.api.dependencies.authorization import (
    require_observer,
)
from app.api.routes import reports as reports_routes
from app.main import app
from app.schemas.visual_recognition import (
    VisualRecognitionResponse,
    VisualThreatSuggestion,
)


def override_observer():
    return {
        "user_id": 42,
        "role": "observer",
    }


def override_coordinator():
    return {
        "user_id": 12,
        "role": "case_coordinator",
    }


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_visual_recognition_requires_authentication(client):
    response = client.post(
        "/api/v1/reports/visual-recognition",
        files={
            "photo": (
                "reef.jpg",
                b"\xff\xd8\xffimage",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 401


def test_visual_recognition_rejects_non_observer(client):
    app.dependency_overrides[
        require_authentication
    ] = override_coordinator

    response = client.post(
        "/api/v1/reports/visual-recognition",
        files={
            "photo": (
                "reef.jpg",
                b"\xff\xd8\xffimage",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 403


def test_visual_recognition_returns_frozen_contract(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer
    service_mock = AsyncMock(
        return_value=VisualRecognitionResponse(
            status="recognized",
            suggested_threat=VisualThreatSuggestion(
                code="ghost_gear",
                label="Ghost fishing gear",
            ),
            confidence=0.87,
            warning=None,
        )
    )
    monkeypatch.setattr(
        reports_routes,
        "recognize_visual_threat",
        service_mock,
    )

    response = client.post(
        "/api/v1/reports/visual-recognition",
        files={
            "photo": (
                "reef.jpg",
                b"\xff\xd8\xffimage",
                "image/jpeg",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "recognized",
        "suggestedThreat": {
            "code": "ghost_gear",
            "label": "Ghost fishing gear",
        },
        "confidence": 0.87,
        "warning": None,
    }
    service_mock.assert_awaited_once_with(
        content=b"\xff\xd8\xffimage",
        content_type="image/jpeg",
    )


def test_visual_recognition_rejects_unsupported_photo(
    client,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    response = client.post(
        "/api/v1/reports/visual-recognition",
        files={
            "photo": (
                "reef.gif",
                b"GIF89a",
                "image/gif",
            )
        },
    )

    assert response.status_code == 400
    assert "JPEG, PNG and WebP" in response.json()["detail"]


def test_visual_recognition_requires_photo_field(client):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    response = client.post(
        "/api/v1/reports/visual-recognition"
    )

    assert response.status_code == 422
