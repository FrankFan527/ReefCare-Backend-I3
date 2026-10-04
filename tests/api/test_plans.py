from datetime import (
    date,
    datetime,
    timezone,
)
from unittest.mock import (
    AsyncMock,
)

import pytest
from fastapi.testclient import (
    TestClient,
)

from app.api.dependencies.auth import (
    require_authentication,
)
from app.api.routes import (
    plans as plans_routes,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.schemas.plan import (
    SavedPlanListResponse,
    SavedPlanResponse,
)


BASE = "/api/v1/plans"

NOW = datetime(
    2026,
    10,
    4,
    8,
    0,
    tzinfo=timezone.utc,
)


async def override_db():
    yield object()


@pytest.fixture(autouse=True)
def clean_overrides():
    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


@pytest.fixture
def client():
    app.dependency_overrides[
        get_db_session
    ] = override_db

    app.dependency_overrides[
        require_authentication
    ] = lambda: {
        "user_id": 77,
        "role": "observer",
        "display_name": "Observer",
    }

    with TestClient(
        app
    ) as test_client:
        yield test_client


def response_plan():
    return SavedPlanResponse(
        plan_id=12,

        name="Redang dive plan",

        area_code="redang",

        planned_date=date(
            2026,
            10,
            10,
        ),

        dive_site_ids=[
            21,
            23,
        ],

        created_at=NOW,
        updated_at=NOW,
    )


def test_list_plans_requires_authentication(
    client,
):
    app.dependency_overrides.pop(
        require_authentication
    )

    response = client.get(
        BASE
    )

    assert response.status_code == 401


def test_non_observer_is_rejected(
    client,
):
    app.dependency_overrides[
        require_authentication
    ] = lambda: {
        "user_id": 88,
        "role": "case_coordinator",
        "display_name": "Coordinator",
    }

    response = client.get(
        BASE
    )

    assert response.status_code == 403


def test_list_returns_fixed_items_shape(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            SavedPlanListResponse(
                items=[
                    response_plan()
                ]
            )
        )
    )

    monkeypatch.setattr(
        plans_routes,
        "list_my_saved_plans",
        service_mock,
    )

    response = client.get(
        BASE
    )

    assert response.status_code == 200

    body = response.json()

    assert "items" in body

    assert isinstance(
        body["items"],
        list,
    )

    assert (
        body["items"][0]
        ["planId"]
        == 12
    )

    assert (
        body["items"][0]
        ["areaCode"]
        == "redang"
    )

    assert (
        body["items"][0]
        ["diveSiteIds"]
        == [21, 23]
    )

    service_mock.assert_awaited_once()

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "observer_id"
        ]
        == 77
    )


def test_create_plan_returns_201_and_camel_case(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            response_plan()
        )
    )

    monkeypatch.setattr(
        plans_routes,
        "create_my_saved_plan",
        service_mock,
    )

    response = client.post(
        BASE,
        json={
            "name":
                "Redang dive plan",

            "areaCode":
                "REDANG",

            "plannedDate":
                "2026-10-10",

            "diveSiteIds":
                [21, 23],
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body[
        "planId"
    ] == 12

    assert body[
        "areaCode"
    ] == "redang"

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "observer_id"
        ]
        == 77
    )

    assert (
        kwargs[
            "area_code"
        ]
        == "redang"
    )


def test_duplicate_site_ids_are_rejected(
    client,
):
    response = client.post(
        BASE,
        json={
            "name":
                "Redang dive plan",

            "areaCode":
                "redang",

            "plannedDate":
                "2026-10-10",

            "diveSiteIds":
                [21, 21],
        },
    )

    assert response.status_code == 422


def test_blank_name_is_rejected(
    client,
):
    response = client.post(
        BASE,
        json={
            "name":
                "   ",

            "areaCode":
                "redang",

            "plannedDate":
                "2026-10-10",

            "diveSiteIds":
                [21],
        },
    )

    assert response.status_code == 422


def test_get_plan_passes_authenticated_owner(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            response_plan()
        )
    )

    monkeypatch.setattr(
        plans_routes,
        "get_my_saved_plan",
        service_mock,
    )

    response = client.get(
        f"{BASE}/12"
    )

    assert response.status_code == 200

    service_mock.assert_awaited_once_with(
        db=service_mock.await_args.kwargs[
            "db"
        ],
        observer_id=77,
        plan_id=12,
    )


def test_patch_plan_uses_complete_write_contract(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            response_plan()
        )
    )

    monkeypatch.setattr(
        plans_routes,
        "update_my_saved_plan",
        service_mock,
    )

    response = client.patch(
        f"{BASE}/12",
        json={
            "name":
                "Updated plan",

            "areaCode":
                "redang",

            "plannedDate":
                "2026-10-11",

            "diveSiteIds":
                [23],
        },
    )

    assert response.status_code == 200

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "observer_id"
        ]
        == 77
    )

    assert (
        kwargs[
            "plan_id"
        ]
        == 12
    )

    assert (
        kwargs[
            "dive_site_ids"
        ]
        == [23]
    )


def test_delete_plan_returns_204(
    client,
    monkeypatch,
):
    service_mock = AsyncMock()

    monkeypatch.setattr(
        plans_routes,
        "delete_my_saved_plan",
        service_mock,
    )

    response = client.delete(
        f"{BASE}/12"
    )

    assert response.status_code == 204

    assert response.content == b""

    service_mock.assert_awaited_once()

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "observer_id"
        ]
        == 77
    )

    assert (
        kwargs[
            "plan_id"
        ]
        == 12
    )


def test_openapi_contains_all_saved_plan_routes(
    client,
):
    paths = (
        app.openapi()[
            "paths"
        ]
    )

    assert (
        BASE
        in paths
    )

    assert (
        f"{BASE}/{{plan_id}}"
        in paths
    )

    assert {
        "get",
        "post",
    } <= set(
        paths[
            BASE
        ]
    )

    assert {
        "get",
        "patch",
        "delete",
    } <= set(
        paths[
            f"{BASE}/{{plan_id}}"
        ]
    )