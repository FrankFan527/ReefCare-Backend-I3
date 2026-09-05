from datetime import (
    datetime,
    timedelta,
    timezone,
)
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.auth import (
    require_authentication,
)

from app.api.dependencies.authorization import (
    require_observer,
)
from app.api.routes import (
    reports as reports_routes,
)
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.db.session import get_db_session
from app.main import app
from app.schemas.report import (
    ObserverReportDetailResponse,
    ObserverReportListResponse,
    ObserverReportSummary,
    ObserverTimelineEvent,
    ObserverTimelineResponse,
)


NOW = datetime(
    2026,
    8,
    29,
    6,
    0,
    tzinfo=timezone.utc,
)


async def override_db_session():
    # No real database for API route tests.
    yield object()


def override_observer():
    return {
        "user_id": 42,
        "role": "observer",
    }


def override_coordinator():
    return {
        "user_id": 12,
        "role": "case_coordinator",
        "display_name": "Test Coordinator",
    }


def make_token(
    *,
    user_id: int,
    role: str,
) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "exp": (
                datetime.now(
                    timezone.utc
                )
                + timedelta(minutes=5)
            ),
        },
        settings.jwt_secret_key,
        algorithm=(
            settings.jwt_algorithm
        ),
    )


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


@pytest.fixture
def client():
    app.dependency_overrides[
        get_db_session
    ] = override_db_session

    with TestClient(app) as test_client:
        yield test_client


def test_my_reports_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/reports/mine"
    )

    assert response.status_code == 401


def test_my_reports_rejects_non_observer_role(
    client,
):
    app.dependency_overrides[
        require_authentication
    ] = override_coordinator

    response = client.get(
        "/api/v1/reports/mine",
    )

    assert response.status_code == 403


def test_my_reports_returns_camel_case_observer_safe_response(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    service_mock = AsyncMock(
        return_value=(
            ObserverReportListResponse(
                items=[
                    ObserverReportSummary(
                        report_reference=(
                            "RC-0001"
                        ),
                        threat_category=(
                            "Ghost fishing gear"
                        ),
                        general_location=(
                            "Tioman Island"
                        ),
                        status="received",
                        status_label=(
                            "Report received"
                        ),
                        outcome=None,
                        submitted_at=NOW,
                    )
                ],
                page=1,
                page_size=20,
                total=1,
            )
        )
    )

    monkeypatch.setattr(
        reports_routes,
        "list_observer_reports",
        service_mock,
    )

    response = client.get(
        (
            "/api/v1/reports/mine"
            "?status=received"
            "&page=1"
            "&pageSize=20"
        )
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["page"] == 1
    assert payload["pageSize"] == 20
    assert payload["total"] == 1

    assert (
        payload["items"][0]
        ["reportReference"]
        == "RC-0001"
    )

    assert (
        payload["items"][0]["status"]
        == "received"
    )

    assert (
        payload["items"][0]
        ["statusLabel"]
        == "Report received"
    )

    kwargs = (
        service_mock.await_args.kwargs
    )

    assert kwargs["observer_id"] == 42

    assert (
        kwargs["status_filter"].value
        == "received"
    )


def test_my_report_returns_404_when_report_is_not_in_observer_scope(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    service_mock = AsyncMock(
        side_effect=NotFoundError(
            "Report not found"
        )
    )

    monkeypatch.setattr(
        reports_routes,
        "get_observer_report",
        service_mock,
    )

    response = client.get(
        "/api/v1/reports/RC-9999"
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Report not found"
    }


def test_my_report_returns_observer_safe_detail(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    service_mock = AsyncMock(
        return_value=(
            ObserverReportDetailResponse(
                report_reference=(
                    "RC-0001"
                ),
                threat_category=(
                    "Ghost fishing gear"
                ),
                description=(
                    "Large fishing net "
                    "tangled around coral."
                ),
                observed_at=NOW,
                estimated_depth_metres=15.0,
                general_location=(
                    "Tioman Island"
                ),
                dive_site="Tiger Reef",
                precise_location=None,
                status="received",
                status_label=(
                    "Report received"
                ),
                outcome=None,
                information_request_reason=(
                    None
                ),
                closure=None,
                submitted_at=NOW,
            )
        )
    )

    monkeypatch.setattr(
        reports_routes,
        "get_observer_report",
        service_mock,
    )

    response = client.get(
        "/api/v1/reports/RC-0001"
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["reportReference"]
        == "RC-0001"
    )

    assert (
        payload["threatCategory"]
        == "Ghost fishing gear"
    )

    assert (
        payload["statusLabel"]
        == "Report received"
    )

    assert "claimedByUserId" not in payload
    assert "decisionNote" not in payload
    assert "fileReference" not in payload


def test_report_timeline_returns_plain_language_events(
    client,
    monkeypatch,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    service_mock = AsyncMock(
        return_value=(
            ObserverTimelineResponse(
                report_reference=(
                    "RC-0002"
                ),
                timeline=[
                    ObserverTimelineEvent(
                        status_label=(
                            "Report received"
                        ),
                        occurred_at=NOW,
                    ),
                    ObserverTimelineEvent(
                        status_label=(
                            "A case coordinator "
                            "has your report"
                        ),
                        occurred_at=NOW,
                    ),
                    ObserverTimelineEvent(
                        status_label=(
                            "Being reviewed"
                        ),
                        occurred_at=NOW,
                    ),
                ],
            )
        )
    )

    monkeypatch.setattr(
        reports_routes,
        "get_observer_report_timeline",
        service_mock,
    )

    response = client.get(
        (
            "/api/v1/reports/"
            "RC-0002/timeline"
        )
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["reportReference"]
        == "RC-0002"
    )

    assert [
        event["statusLabel"]
        for event in payload["timeline"]
    ] == [
        "Report received",
        (
            "A case coordinator has "
            "your report"
        ),
        "Being reviewed",
    ]


def test_my_reports_rejects_page_size_over_100(
    client,
):
    app.dependency_overrides[
        require_observer
    ] = override_observer

    response = client.get(
        (
            "/api/v1/reports/mine"
            "?pageSize=101"
        )
    )

    assert response.status_code == 422