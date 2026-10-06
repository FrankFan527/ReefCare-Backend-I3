"""The documented query controls whether corrected follow-ups are included."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import require_coordinator
from app.api.dependencies.db import get_db_session
from app.api.routes.follow_ups import router
from app.services import follow_up_service


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/coordinator")
    app.dependency_overrides[require_coordinator] = lambda: {"user_id": 12}

    async def no_database():
        yield object()

    app.dependency_overrides[get_db_session] = no_database

    async def history(*, db, report_reference, coordinator_id, include_superseded):
        # The repository/service boundary is stubbed; the real HTTP route
        # must correctly interpret the client's query before reaching it.
        return {
            "report_reference": report_reference,
            "items": [],
            "total": 0,
            "message": "Full history" if include_superseded else "Current history",
        }

    monkeypatch.setattr(follow_up_service, "list_follow_ups_for_owned_case", history)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("query,expected", [
    ("", "Current history"),
    ("?includeSuperseded=true", "Full history"),
    ("?includeSuperseded=false", "Current history"),
    ("?include_superseded=true", "Full history"),
    ("?include_superseded=false", "Current history"),
    ("?includeSuperseded=false&include_superseded=true", "Current history"),
    ("?includeSuperseded=true&include_superseded=false", "Full history"),
])
def test_query_selects_requested_history(client, query, expected):
    response = client.get(f"/coordinator/reports/RC-1/follow-ups{query}")
    assert response.status_code == 200
    assert response.json()["message"] == expected


@pytest.mark.parametrize("name", ["includeSuperseded", "include_superseded"])
def test_invalid_boolean_is_rejected(client, name):
    response = client.get(f"/coordinator/reports/RC-1/follow-ups?{name}=not-a-bool")
    assert response.status_code == 422
