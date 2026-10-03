from datetime import (
    date,
    datetime,
)
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import (
    TestClient,
)

from app.api.routes import (
    planning as planning_routes,
)
from app.core.enums import (
    PlanningBand,
    SeasonalState,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.schemas.planning import (
    DateComparisonDay,
    DateComparisonResponse,
    PlanningBandBreakdown,
    PlanningConditionSignals,
    SeasonalCalendarResponse,
    SeasonalMonthResponse,
    SiteComparisonItem,
    SiteComparisonResponse,
)


BASE = (
    "/api/v1/public/planning"
)

RETRIEVED_AT = (
    datetime.fromisoformat(
        "2026-10-03T08:00:00+08:00"
    )
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


def test_seasonality_is_public_and_returns_camel_case(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            SeasonalCalendarResponse(
                area_code="redang",

                source=None,
                basis=None,
                reviewed_at=None,

                months=[
                    SeasonalMonthResponse(
                        month=1,
                        state=(
                            SeasonalState
                            .UNREVIEWED
                        ),
                        headline=(
                            "Reviewed seasonal "
                            "guidance unavailable"
                        ),
                        detail=None,
                    )
                ],
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "get_seasonal_calendar",
        service_mock,
    )

    response = client.get(
        (
            f"{BASE}/areas/"
            "redang/seasonality"
        )
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["areaCode"]
        == "redang"
    )

    assert (
        body["months"][0]["state"]
        == "unreviewed"
    )

    assert "area_code" not in body
    assert "reviewed_at" not in body

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs["area_code"]
        == "redang"
    )


def test_area_code_is_normalised_to_lowercase(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            SeasonalCalendarResponse(
                area_code="redang",
                source=None,
                basis=None,
                reviewed_at=None,
                months=[],
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "get_seasonal_calendar",
        service_mock,
    )

    response = client.get(
        (
            f"{BASE}/areas/"
            "REDANG/seasonality"
        )
    )

    assert response.status_code == 200

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs["area_code"]
        == "redang"
    )


def test_date_comparison_uses_from_and_to_query_aliases(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            DateComparisonResponse(
                area_code="redang",

                rule_version="i3-draft-1",

                source="Open-Meteo",

                retrieved_at=(
                    RETRIEVED_AT
                ),

                days=[
                    DateComparisonDay(
                        date=date(
                            2026,
                            10,
                            3,
                        ),

                        band=(
                            PlanningBand
                            .MIXED
                        ),

                        assessable_sites=3,
                        total_sites=4,

                        breakdown=(
                            PlanningBandBreakdown(
                                more_favourable=1,
                                mixed=1,
                                less_favourable=1,
                            )
                        ),

                        signals=(
                            PlanningConditionSignals(
                                wave_height_max_m=1.0,
                                wind_speed_max_kmh=14.0,
                                precipitation_probability_max_pct=30.0,
                            )
                        ),

                        reasons=[
                            "Example explanation"
                        ],
                    )
                ],
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "compare_travel_dates",
        service_mock,
    )

    response = client.get(
        (
            f"{BASE}/areas/redang/dates"
            "?from=2026-10-03"
            "&to=2026-10-04"
        )
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["ruleVersion"]
        == "i3-draft-1"
    )

    assert (
        body["days"][0]
        ["assessableSites"]
        == 3
    )

    assert (
        body["days"][0]
        ["breakdown"]
        ["moreFavourable"]
        == 1
    )

    assert (
        body["days"][0]
        ["signals"]
        ["waveHeightMaxM"]
        == 1.0
    )

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs["from_date"]
        == date(
            2026,
            10,
            3,
        )
    )

    assert (
        kwargs["to_date"]
        == date(
            2026,
            10,
            4,
        )
    )


def test_date_comparison_requires_both_dates(
    client,
):
    response = client.get(
        (
            f"{BASE}/areas/redang/dates"
            "?from=2026-10-03"
        )
    )

    assert response.status_code == 422


def test_date_comparison_rejects_invalid_date_format(
    client,
):
    response = client.get(
        (
            f"{BASE}/areas/redang/dates"
            "?from=not-a-date"
            "&to=2026-10-04"
        )
    )

    assert response.status_code == 422


def test_site_comparison_is_public_and_returns_camel_case(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            SiteComparisonResponse(
                area_code="redang",

                date=date(
                    2026,
                    10,
                    3,
                ),

                rule_version="i3-draft-1",

                source="Open-Meteo",

                retrieved_at=(
                    RETRIEVED_AT
                ),

                sites=[
                    SiteComparisonItem(
                        dive_site_id=23,

                        site_name="Test Site",

                        band=(
                            PlanningBand
                            .MORE_FAVOURABLE
                        ),

                        wave_height_max_m=0.6,

                        wind_speed_max_kmh=9.0,

                        precipitation_probability_max_pct=20.0,

                        reason=(
                            "Conditions are within "
                            "the current thresholds."
                        ),
                    )
                ],
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "compare_sites_for_date",
        service_mock,
    )

    response = client.get(
        (
            f"{BASE}/areas/redang/sites"
            "?date=2026-10-03"
        )
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["areaCode"]
        == "redang"
    )

    assert (
        body["sites"][0]
        ["diveSiteId"]
        == 23
    )

    assert (
        body["sites"][0]
        ["siteName"]
        == "Test Site"
    )

    assert (
        body["sites"][0]
        ["waveHeightMaxM"]
        == 0.6
    )

    assert (
        body["sites"][0]
        ["windSpeedMaxKmh"]
        == 9.0
    )

    assert "dive_site_id" not in (
        body["sites"][0]
    )

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs["requested_date"]
        == date(
            2026,
            10,
            3,
        )
    )


def test_site_comparison_requires_date_query(
    client,
):
    response = client.get(
        (
            f"{BASE}/areas/"
            "redang/sites"
        )
    )

    assert response.status_code == 422


def test_site_comparison_can_return_not_assessable(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=(
            SiteComparisonResponse(
                area_code="redang",

                date=date(
                    2026,
                    10,
                    3,
                ),

                rule_version="i3-draft-1",

                source="Open-Meteo",

                retrieved_at=None,

                sites=[
                    SiteComparisonItem(
                        dive_site_id=99,

                        site_name=(
                            "Unconfigured Site"
                        ),

                        band=(
                            PlanningBand
                            .NOT_ASSESSABLE
                        ),

                        wave_height_max_m=None,
                        wind_speed_max_kmh=None,

                        precipitation_probability_max_pct=None,

                        reason=(
                            "Site position unavailable."
                        ),
                    )
                ],
            )
        )
    )

    monkeypatch.setattr(
        planning_routes,
        "compare_sites_for_date",
        service_mock,
    )

    response = client.get(
        (
            f"{BASE}/areas/redang/sites"
            "?date=2026-10-03"
        )
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["sites"][0]["band"]
        == "not_assessable"
    )

    assert (
        body["sites"][0]
        ["waveHeightMaxM"]
        is None
    )


def test_openapi_exposes_all_three_public_planning_routes(
    client,
):
    paths = app.openapi()[
        "paths"
    ]

    assert (
        f"{BASE}/areas/"
        "{area_code}/seasonality"
        in paths
    )

    assert (
        f"{BASE}/areas/"
        "{area_code}/dates"
        in paths
    )

    assert (
        f"{BASE}/areas/"
        "{area_code}/sites"
        in paths
    )


def test_openapi_uses_frontend_query_parameter_names(
    client,
):
    paths = app.openapi()[
        "paths"
    ]

    date_operation = paths[
        (
            f"{BASE}/areas/"
            "{area_code}/dates"
        )
    ]["get"]

    parameter_names = {
        parameter["name"]
        for parameter
        in date_operation[
            "parameters"
        ]
    }

    assert {
        "area_code",
        "from",
        "to",
    } <= parameter_names

    site_operation = paths[
        (
            f"{BASE}/areas/"
            "{area_code}/sites"
        )
    ]["get"]

    site_parameter_names = {
        parameter["name"]
        for parameter
        in site_operation[
            "parameters"
        ]
    }

    assert {
        "area_code",
        "date",
    } <= site_parameter_names