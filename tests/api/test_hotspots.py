from datetime import (
    datetime,
    timezone,
)
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies.auth import (
    require_authentication,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.services import (
    case_service,
    hotspot_service as service,
)


BASE = (
    "/api/v1/coordinator"
)

PERIOD = {
    "observedFrom":
        "2026-09-01",

    "observedTo":
        "2026-09-13",

    "interval":
        "day",
}

ROUTES = [
    "/hotspots",
    "/hotspots/options",
    "/hotspots/reports",
    "/hotspots/reports/RC-001/intake",
    "/reports/RC-001/hotspot-context",
]


@pytest.fixture
def client(
    monkeypatch,
):
    app.dependency_overrides.clear()

    async def db():
        yield AsyncMock()

    app.dependency_overrides[
        get_db_session
    ] = db

    app.dependency_overrides[
        require_authentication
    ] = lambda: {
        "user_id": 12,
        "role":
            "case_coordinator",
    }

    monkeypatch.setattr(
        service.repository,
        "get_analysis",
        AsyncMock(
            return_value={
                "groups": [],
                "matching_report_count":
                    0,
                "included_report_count":
                    0,
                "undated_report_count":
                    0,
                "analysed_at":
                    datetime.now(
                        timezone.utc
                    ),
            }
        ),
    )

    with TestClient(
        app
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "route",
    ROUTES,
)
def test_anonymous_is_rejected(
    client,
    route,
):
    app.dependency_overrides.pop(
        require_authentication
    )

    assert (
        client.get(
            BASE + route
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "role",
    [
        "observer",
        "system_administrator",
        "dive_operator",
        "conservation_responder",
    ],
)
@pytest.mark.parametrize(
    "route",
    ROUTES,
)
def test_coordinator_role_required_on_every_endpoint(
    client,
    route,
    role,
):
    app.dependency_overrides[
        require_authentication
    ] = lambda: {
        "user_id": 99,
        "role": role,
    }

    assert (
        client.get(
            BASE + route
        ).status_code
        == 403
    )


def test_camel_case_filters_echo_and_no_matches(
    client,
):
    response = client.get(
        BASE + "/hotspots",
        params={
            **PERIOD,
            "siteId": 42,
            "threat": "unsure",
        },
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert (
        body["state"]
        == "no_matches"
    )

    assert (
        body["filters"][
            "siteId"
        ]
        == 42
    )

    assert (
        body["filters"][
            "threat"
        ]
        == "unsure"
    )

    assert (
        body["filters"][
            "observedFrom"
        ]
        == "2026-09-01"
    )

    assert (
        body["filters"][
            "timezone"
        ]
        == "Asia/Kuala_Lumpur"
    )

    assert (
        response.headers[
            "cache-control"
        ]
        == "private, no-store"
    )


@pytest.mark.parametrize(
    "params",
    [
        {
            "observedFrom":
                "2026-09-01"
        },
        {
            "siteId": -1
        },
        {
            "threat":
                "invalid"
        },
        {
            "observedFrom":
                "2026-09-10",
            "observedTo":
                "2026-09-01",
        },
        {
            "observedFrom":
                "2024-01-01",
            "observedTo":
                "2026-01-01",
        },
        {
            "latitude":
                1.123456
        },
        {
            "radius":
                100
        },
        {
            "interval":
                "hour"
        },
    ],
)
def test_invalid_or_unsupported_query_returns_422(
    client,
    params,
):
    assert (
        client.get(
            BASE + "/hotspots",
            params=params,
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "params",
    [
        {
            "pageSize": 101
        },
        {
            "page": 0
        },
        {
            "ownerId": 99
        },
    ],
)
def test_invalid_pagination_and_owner_override(
    client,
    params,
):
    assert (
        client.get(
            BASE + "/hotspots/reports",
            params=params,
        ).status_code
        == 422
    )


def test_database_failure_is_503_with_null_counts(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        service.repository,
        "get_analysis",
        AsyncMock(
            side_effect=(
                SQLAlchemyError(
                    "secret DSN"
                )
            )
        ),
    )

    response = client.get(
        BASE + "/hotspots",
        params=PERIOD,
    )

    assert (
        response.status_code
        == 503
    )

    assert (
        response.headers[
            "retry-after"
        ]
        == "30"
    )

    body = response.json()

    assert (
        body["state"]
        == "unavailable"
    )

    assert (
        body["summary"]
        is None
    )

    assert (
        body["dataQuality"]
        is None
    )

    assert (
        body[
            "lastSuccessfulUpdateAt"
        ]
        is None
    )

    assert (
        "secret DSN"
        not in response.text
    )


def test_options_include_all_five_categories_and_no_coordinates(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        service.repository,
        "list_sites",
        AsyncMock(
            return_value=[
                {
                    "site_id":
                        1,

                    "site_name":
                        "Named site",

                    "area":
                        "Area",

                    "region":
                        "Region",

                    "centre_latitude":
                        1.123456,

                    "centre_longitude":
                        104.123456,
                }
            ]
        ),
    )

    body = client.get(
        BASE
        + "/hotspots/options"
    ).json()

    assert {
        row["code"]
        for row
        in body[
            "threats"
        ]
    } == set(
        service.THREATS
    )

    assert set(
        body["sites"][0]
    ) == {
        "siteId",
        "name",
        "area",
        "region",
    }


def test_drill_through_rechecks_ownership_and_removes_protected_fields(
    client,
    monkeypatch,
):
    row = dict(
        report_reference="RC-001",
        site_id=1,
        site_name="Named site",
        area="Area",
        region="Region",
        threat_code="unsure",
        threat_label="Unsure",
        observed_at=(
            "2026-09-01"
            "T10:00:00+08:00"
        ),
        submitted_at=(
            "2026-09-02"
            "T10:00:00+08:00"
        ),
        status_code="claimed",
        status_label="Claimed",
        is_closed=False,
        claimed_by_user_id=99,
        owner_display_name=(
            "Another coordinator"
        ),

        # These are deliberately protected.
        description="PRIVATE",
        evidence=["KEY"],
        latitude=1.123456,
        observer_id=55,
    )

    monkeypatch.setattr(
        service.repository,
        "get_intake",
        AsyncMock(
            return_value=row
        ),
    )

    body = client.get(
        BASE
        + "/hotspots/reports/"
        + "RC-001/intake"
    ).json()

    assert (
        body[
            "nextAction"
        ]
        == "assigned_summary"
    )

    assert (
        body[
            "claimApiPath"
        ]
        is None
    )

    assert (
        body[
            "reviewApiPath"
        ]
        is None
    )

    assert not {
        "description",
        "evidence",
        "latitude",
        "observerId",
    } & body.keys()

    # Seeing hotspot intake never authorises protected
    # coordinator case review.
    monkeypatch.setattr(
        case_service,
        "get_case",
        AsyncMock(
            return_value={
                "claimed_by_user_id":
                    99
            }
        ),
    )

    assert (
        client.get(
            BASE
            + "/reports/RC-001"
        ).status_code
        == 403
    )


def test_nonowned_context_is_404(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        service.repository,
        "get_owned_context",
        AsyncMock(
            return_value=None
        ),
    )

    assert (
        client.get(
            BASE
            + "/reports/RC-001"
            + "/hotspot-context"
        ).status_code
        == 404
    )


def test_context_link_round_trips_same_filters(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        service.repository,
        "get_owned_context",
        AsyncMock(
            return_value={
                "report_reference":
                    "RC-001",

                "site_id":
                    8,

                "site_name":
                    "Named site",

                "area":
                    "Area",

                "region":
                    "Region",

                "observed_at":
                    datetime(
                        2025,
                        3,
                        10,
                        18,
                        tzinfo=(
                            timezone.utc
                        ),
                    ),
            }
        ),
    )

    context = client.get(
        BASE
        + "/reports/RC-001"
        + "/hotspot-context"
    ).json()

    analysis = client.get(
        context[
            "analysisApiPath"
        ]
    ).json()

    assert (
        context[
            "filters"
        ]
        ==
        analysis[
            "filters"
        ]
    )

    assert (
        analysis[
            "filters"
        ][
            "observedTo"
        ]
        == "2025-03-11"
    )


def test_openapi_documents_query_aliases_and_failure_model(
    client,
):
    paths = (
        app.openapi()[
            "paths"
        ]
    )

    operation = paths[
        BASE
        + "/hotspots"
    ][
        "get"
    ]

    assert {
        parameter["name"]
        for parameter
        in operation[
            "parameters"
        ]
    } == {
        "siteId",
        "area",
        "region",
        "threat",
        "observedFrom",
        "observedTo",
        "interval",
    }

    assert (
        "503"
        in operation[
            "responses"
        ]
    )

    assert all(
        set(
            paths[
                BASE + route
            ]
        )
        == {
            "get"
        }
        for route
        in [
            "/hotspots",
            "/hotspots/options",
            "/hotspots/reports",
        ]
    )