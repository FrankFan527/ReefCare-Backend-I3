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
from app.schemas.smart_report import (
    SmartReportStructureResponse,
    SmartReportSuggestion,
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


def test_smart_structure_requires_authentication(client):
    response = client.post(
        "/api/v1/reports/smart-structure",
        json={
            "description": (
                "A net was tangled around coral."
            )
        },
    )

    assert response.status_code == 401


def test_smart_structure_rejects_non_observer(client):
    app.dependency_overrides[
        require_authentication
    ] = override_coordinator

    response = client.post(
        "/api/v1/reports/smart-structure",
        json={
            "description": (
                "A net was tangled around coral."
            )
        },
    )

    assert response.status_code == 403


def test_smart_structure_validates_description_length(
    client,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    response = client.post(
        "/api/v1/reports/smart-structure",
        json={"description": "short"},
    )

    assert response.status_code == 422


def test_smart_structure_returns_camel_case_suggestions(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer
    service_mock = AsyncMock(
        return_value=SmartReportStructureResponse(
            available=True,
            suggestions=[
                SmartReportSuggestion(
                    field="possible_threat",
                    label="Possible threat",
                    suggested_value=(
                        "ghost fishing gear"
                    ),
                )
            ],
            missing_information=[
                "approximate size"
            ],
            message=(
                "Review every AI suggestion."
            ),
        )
    )
    monkeypatch.setattr(
        reports_routes,
        "structure_report_description",
        service_mock,
    )

    response = client.post(
        "/api/v1/reports/smart-structure",
        json={
            "description": (
                "A fishing net was tangled around coral."
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "suggestions": [
            {
                "field": "possible_threat",
                "label": "Possible threat",
                "suggestedValue": (
                    "ghost fishing gear"
                ),
            }
        ],
        "missingInformation": [
            "approximate size"
        ],
        "message": "Review every AI suggestion.",
    }
