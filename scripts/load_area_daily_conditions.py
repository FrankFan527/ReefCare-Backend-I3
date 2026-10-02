# ---------------------------------------------------------------------------
# Loads daily marine and weather history from Open-Meteo into
# area_daily_conditions, one row per planning area per day.
#
# Raw values only: no labels, no train/test split, no derived judgement. Those
# are modelling decisions and belong to whoever trains the model.
#
# Run against a dev branch first, verify, then production.
# ---------------------------------------------------------------------------
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

import psycopg
from dotenv import load_dotenv

load_dotenv()

# the repo stores the SQLAlchemy form of the URL; psycopg needs it without the driver suffix
the_database_url: str = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

# the two Open-Meteo endpoints that hold history
the_marine_api_base_url: str = "https://marine-api.open-meteo.com/v1/marine"
the_weather_api_base_url: str = "https://historical-forecast-api.open-meteo.com/v1/forecast"

# the earliest date the marine wave model covers for this region
the_history_start_date: str = "2022-01-01"

# ending two days back, since the most recent days are still being finalised
the_history_end_date: str = (dt.date.today() - dt.timedelta(days=2)).isoformat()

# the timezone for every request, so a "day" means the same thing in every row
the_request_timezone: str = "Asia/Singapore"


def the_fetch_json_from_api(the_base_url: str, the_query_parameters: dict) -> dict:
    """Calls one Open-Meteo endpoint and returns the parsed response."""
    the_full_url = the_base_url + "?" + urllib.parse.urlencode(the_query_parameters)
    with urllib.request.urlopen(the_full_url, timeout=60) as the_response:
        return json.loads(the_response.read().decode("utf-8"))


def the_fetch_marine_history(the_latitude: float, the_longitude: float) -> dict:
    """Daily maximum wave height for one area across the whole history window."""
    return the_fetch_json_from_api(the_marine_api_base_url, {
        "latitude": the_latitude,
        "longitude": the_longitude,
        "start_date": the_history_start_date,
        "end_date": the_history_end_date,
        "daily": "wave_height_max",
        "timezone": the_request_timezone,
    })


def the_fetch_weather_history(the_latitude: float, the_longitude: float) -> dict:
    """Daily maximum wind speed and rainfall total for the same window."""
    return the_fetch_json_from_api(the_weather_api_base_url, {
        "latitude": the_latitude,
        "longitude": the_longitude,
        "start_date": the_history_start_date,
        "end_date": the_history_end_date,
        "daily": "wind_speed_10m_max,precipitation_sum",
        "timezone": the_request_timezone,
    })


def the_build_rows_for_one_area(
    the_area_code: str,
    the_marine_payload: dict,
    the_weather_payload: dict,
) -> list[tuple]:
    """
    Joins the two API responses on date, one tuple per day. A date present in
    only one response still produces a row, with the missing side left as None
    rather than filled in.
    """
    # the date-keyed lookups, so the join never assumes the two lists align
    the_wave_by_date = dict(zip(
        the_marine_payload["daily"]["time"],
        the_marine_payload["daily"]["wave_height_max"],
    ))
    the_wind_by_date = dict(zip(
        the_weather_payload["daily"]["time"],
        the_weather_payload["daily"]["wind_speed_10m_max"],
    ))
    the_rain_by_date = dict(zip(
        the_weather_payload["daily"]["time"],
        the_weather_payload["daily"]["precipitation_sum"],
    ))

    # the grid points each API actually snapped the request to; the two differ
    the_marine_grid_latitude = the_marine_payload["latitude"]
    the_marine_grid_longitude = the_marine_payload["longitude"]
    the_weather_grid_latitude = the_weather_payload["latitude"]
    the_weather_grid_longitude = the_weather_payload["longitude"]

    the_all_dates = sorted(set(the_wave_by_date) | set(the_wind_by_date))

    the_rows_accumulator: list[tuple] = []
    for the_single_date in the_all_dates:
        the_rows_accumulator.append((
            the_area_code,
            the_single_date,
            the_wave_by_date.get(the_single_date),
            the_wind_by_date.get(the_single_date),
            the_rain_by_date.get(the_single_date),
            the_marine_grid_latitude,
            the_marine_grid_longitude,
            the_weather_grid_latitude,
            the_weather_grid_longitude,
            "open-meteo marine (wave_height_max)",
            "open-meteo historical forecast (wind_speed_10m_max, precipitation_sum)",
        ))
    return the_rows_accumulator


def the_load_rows_into_database(the_connection, the_rows: list[tuple]) -> None:
    """Inserts or refreshes rows, keyed on area plus date so re-runs stay safe."""
    the_insert_statement = """
        INSERT INTO area_daily_conditions (
            area_code, observation_date,
            wave_height_max_m, wind_speed_max_kmh, precipitation_sum_mm,
            marine_grid_latitude, marine_grid_longitude,
            weather_grid_latitude, weather_grid_longitude,
            marine_source, weather_source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (area_code, observation_date) DO UPDATE SET
            wave_height_max_m      = EXCLUDED.wave_height_max_m,
            wind_speed_max_kmh     = EXCLUDED.wind_speed_max_kmh,
            precipitation_sum_mm   = EXCLUDED.precipitation_sum_mm,
            marine_grid_latitude   = EXCLUDED.marine_grid_latitude,
            marine_grid_longitude  = EXCLUDED.marine_grid_longitude,
            weather_grid_latitude  = EXCLUDED.weather_grid_latitude,
            weather_grid_longitude = EXCLUDED.weather_grid_longitude,
            marine_source          = EXCLUDED.marine_source,
            weather_source         = EXCLUDED.weather_source,
            retrieved_at           = now()
    """
    with the_connection.cursor() as the_cursor:
        the_cursor.executemany(the_insert_statement, the_rows)


def main() -> None:
    with psycopg.connect(the_database_url) as the_connection:

        # confirm which database and role we landed in before writing anything
        with the_connection.cursor() as the_cursor:
            the_cursor.execute("SELECT current_user, current_database()")
            print("connected as:", the_cursor.fetchone())

        # the configured areas, read from the database rather than hard-coded here
        with the_connection.cursor() as the_cursor:
            the_cursor.execute("""
                SELECT area_code, query_latitude, query_longitude
                FROM planning_area
                ORDER BY area_code
            """)
            the_configured_areas = the_cursor.fetchall()

        print(f"window: {the_history_start_date} to {the_history_end_date}")

        for the_area_code, the_latitude, the_longitude in the_configured_areas:
            print(f"\n{the_area_code}: requesting {the_latitude}, {the_longitude}")

            the_marine_payload = the_fetch_marine_history(float(the_latitude), float(the_longitude))
            time.sleep(1)  # stays well inside the free-tier rate limits
            the_weather_payload = the_fetch_weather_history(float(the_latitude), float(the_longitude))
            time.sleep(1)

            the_rows = the_build_rows_for_one_area(
                the_area_code, the_marine_payload, the_weather_payload
            )

            # a visibility check before anything is written
            the_missing_wave_count = sum(1 for the_row in the_rows if the_row[2] is None)
            the_missing_wind_count = sum(1 for the_row in the_rows if the_row[3] is None)
            print(f"  rows: {len(the_rows)}  "
                  f"missing wave: {the_missing_wave_count}  "
                  f"missing wind: {the_missing_wind_count}")
            print(f"  marine grid:  {the_marine_payload['latitude']}, {the_marine_payload['longitude']}")
            print(f"  weather grid: {the_weather_payload['latitude']}, {the_weather_payload['longitude']}")

            the_load_rows_into_database(the_connection, the_rows)
            the_connection.commit()
            print("  loaded")

        print("\ndone.")


if __name__ == "__main__":
    main()