# ---------------------------------------------------------------------------
# Open-Meteo live forecast adapter for Epic 9.
#
# The existing runtime requirements do not explicitly
# include httpx, so this adapter uses urllib from Python's
# standard library.
#
# urllib is blocking. Every network request therefore runs
# through asyncio.to_thread() and does not block FastAPI's
# event loop.
# ---------------------------------------------------------------------------

import asyncio
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from app.core.config import settings


PROVIDER_NAME: str = "Open-Meteo"


@dataclass(frozen=True)
class ForecastSignals:
    wave_height_max_m: float | None
    wind_speed_max_kmh: float | None

    precipitation_probability_max_pct: (
        float | None
    )


@dataclass(frozen=True)
class PositionForecast:
    key: int

    marine_grid_latitude: float | None
    marine_grid_longitude: float | None

    weather_grid_latitude: float | None
    weather_grid_longitude: float | None

    days: dict[
        date,
        ForecastSignals,
    ]


@dataclass(frozen=True)
class ForecastBatch:
    available: bool
    retrieved_at: datetime

    positions: dict[
        int,
        PositionForecast,
    ]


def _fetch_json_sync(
    base_url: str,
    parameters: dict,
) -> dict | list:
    """
    Perform one blocking provider request.

    This function must only be called through
    asyncio.to_thread().
    """

    query = urllib.parse.urlencode(
        parameters
    )

    request = urllib.request.Request(
        f"{base_url}?{query}",
        headers={
            "User-Agent":
                "ReefCare-MY/Iteration3",
            "Accept":
                "application/json",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=(
            settings
            .planning_forecast_timeout_seconds
        ),
    ) as response:
        return json.loads(
            response
            .read()
            .decode("utf-8")
        )


def _as_payload_list(
    payload: dict | list,
) -> list[dict]:
    """
    Open-Meteo returns one object for one position and an
    array when multiple coordinates are requested.
    """

    if isinstance(
        payload,
        list,
    ):
        return payload

    return [payload]


def _build_daily_lookup(
    payload: dict,
    variable_name: str,
) -> dict[
    date,
    float | None,
]:
    daily = payload.get(
        "daily",
        {},
    )

    times = daily.get(
        "time",
        [],
    )

    values = daily.get(
        variable_name,
        [],
    )

    result: dict[
        date,
        float | None,
    ] = {}

    for (
        raw_date,
        raw_value,
    ) in zip(
        times,
        values,
    ):
        result[
            date.fromisoformat(
                raw_date
            )
        ] = raw_value

    return result


async def fetch_forecast_batch(
    *,
    positions: list[dict],
    start_date: date,
    end_date: date,
) -> ForecastBatch:
    """
    Fetch live forecast signals for several site
    coordinates in one provider batch.

    Each position contains:

        key
        latitude
        longitude

    Provider failures are represented as available=False.
    The public service then returns `unavailable` rather
    than converting a temporary provider problem to an
    application 500.
    """

    timezone = ZoneInfo(
        settings.planning_timezone
    )

    retrieved_at = datetime.now(
        timezone
    )

    if not positions:
        return ForecastBatch(
            available=True,
            retrieved_at=retrieved_at,
            positions={},
        )

    latitudes = ",".join(
        str(
            position[
                "latitude"
            ]
        )
        for position in positions
    )

    longitudes = ",".join(
        str(
            position[
                "longitude"
            ]
        )
        for position in positions
    )

    requested_timezones = ",".join(
        settings.planning_timezone
        for _ in positions
    )

    marine_parameters = {
        "latitude":
            latitudes,

        "longitude":
            longitudes,

        "start_date":
            start_date.isoformat(),

        "end_date":
            end_date.isoformat(),

        "daily":
            "wave_height_max",

        "timezone":
            requested_timezones,
    }

    weather_parameters = {
        "latitude":
            latitudes,

        "longitude":
            longitudes,

        "start_date":
            start_date.isoformat(),

        "end_date":
            end_date.isoformat(),

        "daily": (
            "wind_speed_10m_max,"
            "precipitation_probability_max"
        ),

        "timezone":
            requested_timezones,

        "wind_speed_unit":
            "kmh",
    }

    try:
        marine_task = asyncio.to_thread(
            _fetch_json_sync,
            settings
            .open_meteo_marine_base_url,
            marine_parameters,
        )

        weather_task = asyncio.to_thread(
            _fetch_json_sync,
            settings
            .open_meteo_weather_base_url,
            weather_parameters,
        )

        (
            marine_payload,
            weather_payload,
        ) = await asyncio.gather(
            marine_task,
            weather_task,
        )

    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        json.JSONDecodeError,
        OSError,
    ):
        return ForecastBatch(
            available=False,
            retrieved_at=retrieved_at,
            positions={},
        )

    marine_rows = _as_payload_list(
        marine_payload
    )

    weather_rows = _as_payload_list(
        weather_payload
    )

    if (
        len(marine_rows)
        != len(positions)
        or
        len(weather_rows)
        != len(positions)
    ):
        return ForecastBatch(
            available=False,
            retrieved_at=retrieved_at,
            positions={},
        )

    forecasts: dict[
        int,
        PositionForecast,
    ] = {}

    for index, position in enumerate(
        positions
    ):
        marine = marine_rows[
            index
        ]

        weather = weather_rows[
            index
        ]

        waves = _build_daily_lookup(
            marine,
            "wave_height_max",
        )

        winds = _build_daily_lookup(
            weather,
            "wind_speed_10m_max",
        )

        precipitation = (
            _build_daily_lookup(
                weather,
                (
                    "precipitation_"
                    "probability_max"
                ),
            )
        )

        all_dates = (
            set(waves)
            | set(winds)
            | set(precipitation)
        )

        days: dict[
            date,
            ForecastSignals,
        ] = {}

        for single_date in all_dates:
            days[
                single_date
            ] = ForecastSignals(
                wave_height_max_m=(
                    waves.get(
                        single_date
                    )
                ),
                wind_speed_max_kmh=(
                    winds.get(
                        single_date
                    )
                ),
                precipitation_probability_max_pct=(
                    precipitation.get(
                        single_date
                    )
                ),
            )

        forecasts[
            position["key"]
        ] = PositionForecast(
            key=position["key"],

            marine_grid_latitude=(
                marine.get(
                    "latitude"
                )
            ),

            marine_grid_longitude=(
                marine.get(
                    "longitude"
                )
            ),

            weather_grid_latitude=(
                weather.get(
                    "latitude"
                )
            ),

            weather_grid_longitude=(
                weather.get(
                    "longitude"
                )
            ),

            days=days,
        )

    return ForecastBatch(
        available=True,
        retrieved_at=retrieved_at,
        positions=forecasts,
    )