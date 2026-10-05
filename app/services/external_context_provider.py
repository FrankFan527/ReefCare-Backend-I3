# ---------------------------------------------------------------------------
# US8.3 NOAA Coral Reef Watch adapter.
#
# Source: the CRW Operational Daily Near-Real-Time Global 5 km Satellite Coral
# Bleaching Monitoring Products (CoralTemp v3.1), served through ERDDAP
# griddap from two mirrors, tried in order (settings.noaa_crw_base_urls):
#
#   1. PacIOOS, Hawaii — dataset dhw_5km, the upstream publisher
#   2. NOAA CoastWatch West Coast — dataset NOAA_DHW, a re-serve of (1)
#
# Both use the same variable names, so one query and one parser serve both.
# On 2026-10-05 the PacIOOS mirror answered from Malaysia and the CoastWatch
# one refused connections, which is why PacIOOS goes first.
#
# Two values are read, both standard reef-condition indicators:
#
#   CRW_DHW   degree heating weeks, in Celsius-weeks. Accumulated heat stress
#             over the preceding 12 weeks. NOAA's own guidance: significant
#             bleaching is expected around 4, widespread bleaching and
#             mortality around 8.
#   CRW_BAA   bleaching alert area, a published category from 0 to 4.
#
# Sea surface temperature is available from the same request and deliberately
# not read. It is the easiest value to misread as a safety signal, which
# US8.3 AC3 rules out.
#
# This module follows the Open-Meteo adapter's approach rather than adding a
# dependency: urllib from the standard library, run through asyncio.to_thread
# so the blocking call never holds the event loop.
#
# Nothing here raises. A caller gets ProviderResult.available = False and
# decides what to do, because US8.3 AC4 requires the rest of the platform to
# keep working when the provider does not.
# ---------------------------------------------------------------------------

import asyncio
import csv
import io
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.core.config import settings


logger = logging.getLogger(__name__)


PROVIDER_CODE: str = "noaa_crw"
PROVIDER_NAME: str = "NOAA Coral Reef Watch"


# the ERDDAP variable names, mapped to our canonical context type codes
THE_DHW_VARIABLE: str = "CRW_DHW"
THE_BAA_VARIABLE: str = "CRW_BAA"

THE_DHW_CONTEXT_TYPE: str = "degree_heating_week"
THE_BAA_CONTEXT_TYPE: str = "bleaching_alert_level"


# values NOAA uses for land, ice and missing pixels. An unsigned byte fill of
# -5 arrives as 251, so both forms are refused.
THE_MISSING_NUMERIC_VALUES: frozenset[float] = frozenset({-327.68, -5.0, 251.0})


# the provider's own published categories, used verbatim so ReefCare never
# invents a severity word NOAA did not publish
THE_ALERT_LEVEL_LABELS: dict[int, str] = {
    0: "No stress",
    1: "Bleaching watch",
    2: "Bleaching warning",
    3: "Bleaching alert level 1",
    4: "Bleaching alert level 2",
}


@dataclass(frozen=True)
class ProviderValue:
    context_type_code: str

    numeric_value: float | None
    display_value: str

    represented_date: date


@dataclass
class ProviderResult:
    """
    One fetch attempt. available is False for every failure mode: a timeout,
    an HTTP error, an unreadable response, or a grid cell with no usable data.
    """

    available: bool
    retrieved_at: datetime

    grid_latitude: float | None = None
    grid_longitude: float | None = None

    values: list[ProviderValue] = field(default_factory=list)

    unavailable_reason: str | None = None


def configured_base_urls() -> list[str]:
    return [
        the_url.strip()
        for the_url in settings.noaa_crw_base_urls.split(",")
        if the_url.strip()
    ]


def build_request_url(
    base_url: str,
    latitude: float,
    longitude: float,
) -> str:
    """
    A griddap query for the most recent day at one grid cell.

    [(last)] asks ERDDAP for the newest time step, which matters because the
    near-real-time product usually runs a day or two behind today.

    The brackets and parentheses are part of griddap's syntax and are left
    unescaped; only the characters that would otherwise break the URL are
    percent-encoded.
    """

    the_cell = f"[(last)][({latitude})][({longitude})]"

    the_query = (
        f"{THE_DHW_VARIABLE}{the_cell},{THE_BAA_VARIABLE}{the_cell}"
    )

    return (
        f"{base_url}?"
        + urllib.parse.quote(the_query, safe="[]().,:-")
    )


def _fetch_csv_sync(
    url: str,
) -> str:
    """
    One blocking provider request. Only call this through asyncio.to_thread().
    """

    the_request = urllib.request.Request(
        url,
        headers={"User-Agent": "ReefCare-MY/1.0 (FIT5120 capstone)"},
    )

    with urllib.request.urlopen(
        the_request,
        timeout=settings.noaa_crw_timeout_seconds,
    ) as the_response:
        return the_response.read().decode("utf-8", errors="replace")


def parse_numeric(
    the_raw: str,
) -> float | None:
    """
    None for anything that is not a usable measurement: an empty cell, NaN,
    or one of the provider's fill values for land, ice and missing pixels.
    """

    the_text = (the_raw or "").strip()

    if not the_text or the_text.upper() == "NAN":
        return None

    try:
        the_value = float(the_text)

    except ValueError:
        return None

    if the_value in THE_MISSING_NUMERIC_VALUES:
        return None

    return the_value


def parse_response(
    the_csv_text: str,
    the_retrieved_at: datetime,
) -> ProviderResult:
    """
    Read the griddap CSV.

    Line 1 is column names, line 2 is units, and line 3 onwards is data. A
    one-cell request returns a single data row.
    """

    the_rows = list(csv.reader(io.StringIO(the_csv_text)))

    if len(the_rows) < 3:
        return ProviderResult(
            available=False,
            retrieved_at=the_retrieved_at,
            unavailable_reason="The provider returned no data rows",
        )

    the_header = [the_name.strip() for the_name in the_rows[0]]
    the_data = the_rows[2]

    try:
        the_row = dict(zip(the_header, the_data, strict=False))

        the_time_text = the_row["time"].strip()
        the_represented_date = datetime.fromisoformat(
            the_time_text.replace("Z", "+00:00")
        ).date()

        the_grid_latitude = parse_numeric(the_row.get("latitude", ""))
        the_grid_longitude = parse_numeric(the_row.get("longitude", ""))

    except (KeyError, ValueError):
        return ProviderResult(
            available=False,
            retrieved_at=the_retrieved_at,
            unavailable_reason="The provider response could not be read",
        )

    the_values: list[ProviderValue] = []

    the_degree_heating_weeks = parse_numeric(the_row.get(THE_DHW_VARIABLE, ""))

    if the_degree_heating_weeks is not None:
        the_values.append(
            ProviderValue(
                context_type_code=THE_DHW_CONTEXT_TYPE,
                numeric_value=the_degree_heating_weeks,
                display_value=f"{the_degree_heating_weeks:.2f} °C-weeks",
                represented_date=the_represented_date,
            )
        )

    the_alert_value = parse_numeric(the_row.get(THE_BAA_VARIABLE, ""))

    if the_alert_value is not None and int(the_alert_value) in THE_ALERT_LEVEL_LABELS:
        the_alert_level = int(the_alert_value)

        the_values.append(
            ProviderValue(
                context_type_code=THE_BAA_CONTEXT_TYPE,
                numeric_value=float(the_alert_level),
                display_value=THE_ALERT_LEVEL_LABELS[the_alert_level],
                represented_date=the_represented_date,
            )
        )

    if not the_values:
        # a land, ice or masked grid cell. Honest unavailability, not a zero.
        return ProviderResult(
            available=False,
            retrieved_at=the_retrieved_at,
            grid_latitude=the_grid_latitude,
            grid_longitude=the_grid_longitude,
            unavailable_reason="The provider has no usable value for this grid cell",
        )

    return ProviderResult(
        available=True,
        retrieved_at=the_retrieved_at,
        grid_latitude=the_grid_latitude,
        grid_longitude=the_grid_longitude,
        values=the_values,
    )


async def _fetch_from_mirror(
    base_url: str,
    latitude: float,
    longitude: float,
) -> ProviderResult:
    """
    One attempt against one mirror. Never raises.
    """

    the_retrieved_at = datetime.now(timezone.utc)

    the_url = build_request_url(
        base_url=base_url,
        latitude=latitude,
        longitude=longitude,
    )

    try:
        the_csv_text = await asyncio.to_thread(_fetch_csv_sync, the_url)

    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as the_error:
        # the site's coordinate is in the URL, so only the host is logged
        logger.warning(
            "NOAA Coral Reef Watch mirror %s failed: %s",
            urllib.parse.urlsplit(base_url).hostname,
            type(the_error).__name__,
        )

        return ProviderResult(
            available=False,
            retrieved_at=the_retrieved_at,
            unavailable_reason="The provider could not be reached",
        )

    except Exception:
        logger.exception(
            "NOAA Coral Reef Watch mirror %s failed unexpectedly",
            urllib.parse.urlsplit(base_url).hostname,
        )

        return ProviderResult(
            available=False,
            retrieved_at=the_retrieved_at,
            unavailable_reason="The provider could not be reached",
        )

    return parse_response(the_csv_text, the_retrieved_at)


async def fetch_site_context(
    latitude: float,
    longitude: float,
) -> ProviderResult:
    """
    Fetch the newest NOAA values for one position, trying each configured
    mirror in order. Never raises.

    A mirror that answers but has no usable value for this grid cell is not
    retried elsewhere: both mirrors serve the same product, so a land or
    masked cell is masked on both.
    """

    if not settings.external_context_enabled:
        return ProviderResult(
            available=False,
            retrieved_at=datetime.now(timezone.utc),
            unavailable_reason="External context is disabled in this environment",
        )

    the_last_result: ProviderResult | None = None

    for the_base_url in configured_base_urls():
        the_result = await _fetch_from_mirror(
            base_url=the_base_url,
            latitude=latitude,
            longitude=longitude,
        )

        if the_result.available:
            return the_result

        the_last_result = the_result

        # the mirror answered and the cell genuinely has no data
        if the_result.grid_latitude is not None:
            return the_result

    return the_last_result or ProviderResult(
        available=False,
        retrieved_at=datetime.now(timezone.utc),
        unavailable_reason="No provider is configured",
    )
