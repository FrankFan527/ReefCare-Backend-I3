from datetime import (
    date,
    datetime,
)
from unittest.mock import (
    AsyncMock,
)

import pytest
from fastapi.testclient import (
    TestClient,
)

from app.api.routes import (
    planning as planning_routes,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.schemas.planning import (
    PlanningBriefResponse,
)


BASE = (
    "/api/v1/public/planning/brief"
)


async def override_db_session():
    yield object()


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

    with TestClient(
        app
    ) as test_client:
        yield test_client


def test_brief_is_public_and_returns_generated_contract(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            PlanningBriefResponse(
                site_id=23,

                planned_date=date(
                    2026,
                    10,
                    6,
                ),

                status="generated",

                text=(
                    "Paragraph one.\n\n"
                    "Paragraph two."
                ),

                generated_at=(
                    datetime.fromisoformat(
                        "2026-10-04T19:00:00+08:00"
                    )
                ),
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "generate_planning_brief",
        service_mock,
    )

    response = client.post(
        BASE,

        json={
            "siteId":
                23,

            "plannedDate":
                "2026-10-06",
        },
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert body[
        "siteId"
    ] == 23

    assert body[
        "plannedDate"
    ] == "2026-10-06"

    assert body[
        "status"
    ] == "generated"

    assert (
        body[
            "generatedAt"
        ]
        is not None
    )

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "site_id"
        ]
        == 23
    )

    assert (
        kwargs[
            "planned_date"
        ]
        == date(
            2026,
            10,
            6,
        )
    )


def test_ai_failure_contract_is_still_http_200(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        planning_routes,
        "generate_planning_brief",
        AsyncMock(
            return_value=(
                PlanningBriefResponse(
                    site_id=23,

                    planned_date=date(
                        2026,
                        10,
                        6,
                    ),

                    status="unavailable",

                    text=None,

                    generated_at=None,
                )
            )
        ),
    )

    response = client.post(
        BASE,

        json={
            "siteId":
                23,

            "plannedDate":
                "2026-10-06",
        },
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert (
        body["status"]
        == "unavailable"
    )

    assert body["text"] is None

    assert (
        body["generatedAt"]
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "plannedDate":
                "2026-10-06",
        },

        {
            "siteId":
                23,
        },

        {
            "siteId":
                0,

            "plannedDate":
                "2026-10-06",
        },

        {
            "siteId":
                -1,

            "plannedDate":
                "2026-10-06",
        },

        {
            "siteId":
                23,

            "plannedDate":
                "not-a-date",
        },
    ],
)
def test_invalid_request_returns_422(
    client,
    payload,
):
    response = client.post(
        BASE,
        json=payload,
    )

    assert (
        response.status_code
        == 422
    )


def test_client_cannot_supply_forecast_facts(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            PlanningBriefResponse(
                site_id=23,

                planned_date=date(
                    2026,
                    10,
                    6,
                ),

                status="generated",

                text="Brief",

                generated_at=(
                    datetime.fromisoformat(
                        "2026-10-04T19:00:00+08:00"
                    )
                ),
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "generate_planning_brief",
        service_mock,
    )

    response = client.post(
        BASE,

        json={
            "siteId":
                23,

            "plannedDate":
                "2026-10-06",

            # Unknown fields are ignored by the existing
            # APIModel configuration. Most importantly,
            # none are passed into the service.
            "waveHeightMaxM":
                0.1,

            "band":
                "more_favourable",

            "reefCondition":
                "perfect",
        },
    )

    assert (
        response.status_code
        == 200
    )

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert set(
        kwargs
    ) == {
        "db",
        "site_id",
        "planned_date",
    }


def test_openapi_contains_planning_brief_route(
    client,
):
    paths = (
        app.openapi()[
            "paths"
        ]
    )

    assert BASE in paths

    assert (
        "post"
        in paths[
            BASE
        ]
    )