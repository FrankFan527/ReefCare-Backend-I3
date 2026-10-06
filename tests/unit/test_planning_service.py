from datetime import (
    date,
    datetime,
)
from unittest.mock import (
    AsyncMock,
)

import pytest

from app.core.enums import (
    PlanningBand,
    SeasonalState,
)
from app.core.exceptions import (
    NotFoundError,
    RequestValidationError,
)
from app.services import (
    planning_service as service,
)
from app.services.planning_provider_service import (
    ForecastBatch,
    ForecastSignals,
    PositionForecast,
)


FIXED_TODAY = date(
    2026,
    10,
    3,
)


RETRIEVED_AT = datetime.fromisoformat(
    "2026-10-03T08:00:00+08:00"
)


def area():
    return {
        "area_code": "redang",
        "area_label": "Redang Island",
        "query_latitude": 5.7606,
        "query_longitude": 103.0275,
        "site_count": 2,
        "notes": None,
    }


def site(
    *,
    dive_site_id: int,
    name: str,
    latitude: float | None,
    longitude: float | None,
):
    return {
        "dive_site_id":
            dive_site_id,

        "name":
            name,

        "public_area_label":
            "Redang Island",

        "region":
            "Terengganu",

        "centre_latitude":
            latitude,

        "centre_longitude":
            longitude,

        "default_uncertainty_metres":
            500,

        "coordinate_source":
            "reference",

        "is_verified":
            True,
    }


@pytest.fixture(autouse=True)
def fixed_today(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "malaysia_today",
        lambda: FIXED_TODAY,
    )


@pytest.mark.asyncio
async def test_seasonality_returns_all_twelve_months_as_unreviewed(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    result = (
        await service
        .get_seasonal_calendar(
            db=object(),
            area_code="redang",
        )
    )

    assert result.area_code == "redang"

    assert len(result.months) == 12

    assert [
        month.month
        for month in result.months
    ] == list(
        range(1, 13)
    )

    assert all(
        month.state
        == SeasonalState.UNREVIEWED

        for month
        in result.months
    )

    assert result.source is None
    assert result.basis is None
    assert result.reviewed_at is None


@pytest.mark.asyncio
async def test_unknown_area_raises_not_found(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=None
        ),
    )

    with pytest.raises(
        NotFoundError,
        match="Planning area invalid not found",
    ):
        await service.get_seasonal_calendar(
            db=object(),
            area_code="invalid",
        )


@pytest.mark.asyncio
async def test_date_comparison_rejects_inverted_window(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    with pytest.raises(
        RequestValidationError,
        match="from must be on or before to",
    ) as error:
        await service.compare_travel_dates(
            db=object(),
            area_code="redang",
            from_date=date(
                2026,
                10,
                8,
            ),
            to_date=date(
                2026,
                10,
                5,
            ),
        )

    assert (
        error.value.status_code
        == 422
    )

    assert (
        error.value.error_code
        == "validation_error"
    )


@pytest.mark.asyncio
async def test_date_comparison_rejects_more_than_fourteen_days(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    with pytest.raises(
        RequestValidationError,
        match="cannot exceed 14 days",
    ) as error:
        await service.compare_travel_dates(
            db=object(),
            area_code="redang",
            from_date=date(
                2026,
                10,
                1,
            ),
            to_date=date(
                2026,
                10,
                15,
            ),
        )

    assert (
        error.value.status_code
        == 422
    )

    assert (
        error.value.error_code
        == "validation_error"
    )


@pytest.mark.asyncio
async def test_date_outside_horizon_is_returned_not_guessed(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    monkeypatch.setattr(
        service,
        "list_planning_sites",
        AsyncMock(
            return_value=[
                site(
                    dive_site_id=1,
                    name="Site One",
                    latitude=5.7,
                    longitude=103.0,
                ),
            ]
        ),
    )

    provider_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "fetch_forecast_batch",
        provider_mock,
    )

    result = (
        await service
        .compare_travel_dates(
            db=object(),
            area_code="redang",

            from_date=date(
                2026,
                10,
                12,
            ),

            to_date=date(
                2026,
                10,
                12,
            ),
        )
    )

    assert len(result.days) == 1

    assert (
        result.days[0].band
        == PlanningBand.OUT_OF_HORIZON
    )

    assert (
        result.days[0]
        .assessable_sites
        == 0
    )

    provider_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_site_position_is_not_assessable(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    monkeypatch.setattr(
        service,
        "list_planning_sites",
        AsyncMock(
            return_value=[
                site(
                    dive_site_id=23,
                    name="No Coordinate Site",
                    latitude=None,
                    longitude=None,
                ),
            ]
        ),
    )

    provider_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "fetch_forecast_batch",
        provider_mock,
    )

    result = (
        await service
        .compare_sites_for_date(
            db=object(),
            area_code="redang",
            requested_date=FIXED_TODAY,
        )
    )

    assert len(result.sites) == 1

    item = result.sites[0]

    assert (
        item.band
        == PlanningBand.NOT_ASSESSABLE
    )

    assert item.wave_height_max_m is None
    assert item.wind_speed_max_kmh is None

    assert (
        "position unavailable"
        in item.reason.lower()
    )

    provider_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_returns_unavailable_instead_of_raising(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    monkeypatch.setattr(
        service,
        "list_planning_sites",
        AsyncMock(
            return_value=[
                site(
                    dive_site_id=23,
                    name="Site One",
                    latitude=5.7,
                    longitude=103.0,
                ),
            ]
        ),
    )

    monkeypatch.setattr(
        service,
        "fetch_forecast_batch",
        AsyncMock(
            return_value=ForecastBatch(
                available=False,
                retrieved_at=RETRIEVED_AT,
                positions={},
            )
        ),
    )

    result = (
        await service
        .compare_sites_for_date(
            db=object(),
            area_code="redang",
            requested_date=FIXED_TODAY,
        )
    )

    assert (
        result.sites[0].band
        == PlanningBand.UNAVAILABLE
    )

    assert (
        "provider"
        in result.sites[0]
        .reason.lower()
    )


@pytest.mark.asyncio
async def test_site_comparison_returns_live_provider_values(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    monkeypatch.setattr(
        service,
        "list_planning_sites",
        AsyncMock(
            return_value=[
                site(
                    dive_site_id=23,
                    name="Site One",
                    latitude=5.7,
                    longitude=103.0,
                ),
            ]
        ),
    )

    batch = ForecastBatch(
        available=True,
        retrieved_at=RETRIEVED_AT,
        positions={
            23: PositionForecast(
                key=23,

                marine_grid_latitude=5.7,
                marine_grid_longitude=103.0,

                weather_grid_latitude=5.7,
                weather_grid_longitude=103.0,

                days={
                    FIXED_TODAY:
                        ForecastSignals(
                            wave_height_max_m=0.6,
                            wind_speed_max_kmh=9.0,
                            precipitation_probability_max_pct=20.0,
                        )
                },
            )
        },
    )

    monkeypatch.setattr(
        service,
        "fetch_forecast_batch",
        AsyncMock(
            return_value=batch
        ),
    )

    result = (
        await service
        .compare_sites_for_date(
            db=object(),
            area_code="redang",
            requested_date=FIXED_TODAY,
        )
    )

    item = result.sites[0]

    assert (
        item.band
        == PlanningBand.MORE_FAVOURABLE
    )

    assert item.wave_height_max_m == 0.6

    assert (
        item.wind_speed_max_kmh
        == 9.0
    )

    assert (
        item
        .precipitation_probability_max_pct
        == 20.0
    )

    assert result.retrieved_at == RETRIEVED_AT


@pytest.mark.asyncio
async def test_date_comparison_uses_least_favourable_site(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_area",
        AsyncMock(
            return_value=area()
        ),
    )

    monkeypatch.setattr(
        service,
        "list_planning_sites",
        AsyncMock(
            return_value=[
                site(
                    dive_site_id=1,
                    name="Good Site",
                    latitude=5.7,
                    longitude=103.0,
                ),
                site(
                    dive_site_id=2,
                    name="Rough Site",
                    latitude=5.8,
                    longitude=103.1,
                ),
            ]
        ),
    )

    batch = ForecastBatch(
        available=True,
        retrieved_at=RETRIEVED_AT,
        positions={
            1: PositionForecast(
                key=1,

                marine_grid_latitude=5.7,
                marine_grid_longitude=103.0,

                weather_grid_latitude=5.7,
                weather_grid_longitude=103.0,

                days={
                    FIXED_TODAY:
                        ForecastSignals(
                            wave_height_max_m=0.5,
                            wind_speed_max_kmh=8.0,
                            precipitation_probability_max_pct=10.0,
                        )
                },
            ),

            2: PositionForecast(
                key=2,

                marine_grid_latitude=5.8,
                marine_grid_longitude=103.1,

                weather_grid_latitude=5.8,
                weather_grid_longitude=103.1,

                days={
                    FIXED_TODAY:
                        ForecastSignals(
                            wave_height_max_m=1.8,
                            wind_speed_max_kmh=16.0,
                            precipitation_probability_max_pct=30.0,
                        )
                },
            ),
        },
    )

    monkeypatch.setattr(
        service,
        "fetch_forecast_batch",
        AsyncMock(
            return_value=batch
        ),
    )

    result = (
        await service
        .compare_travel_dates(
            db=object(),
            area_code="redang",

            from_date=FIXED_TODAY,
            to_date=FIXED_TODAY,
        )
    )

    day = result.days[0]

    assert (
        day.band
        == PlanningBand.LESS_FAVOURABLE
    )

    assert day.assessable_sites == 2
    assert day.total_sites == 2

    assert (
        day.breakdown.more_favourable
        == 1
    )

    assert (
        day.breakdown.less_favourable
        == 1
    )

    assert (
        day.signals.wave_height_max_m
        == 1.8
    )

    assert (
        day.signals.wind_speed_max_kmh
        == 16.0
    )


@pytest.mark.asyncio
async def test_provider_positions_exclude_sites_without_coordinates():
    sites = [
        site(
            dive_site_id=1,
            name="Valid",
            latitude=5.7,
            longitude=103.0,
        ),
        site(
            dive_site_id=2,
            name="Missing",
            latitude=None,
            longitude=None,
        ),
    ]

    result = service.build_provider_positions(
        sites
    )

    assert result == [
        {
            "key": 1,
            "latitude": 5.7,
            "longitude": 103.0,
        }
    ]