# ---------------------------------------------------------------------------
# US8.3 selected external context — unit tests (no network, no database).
#
# The parser is tested against the exact response NOAA's PacIOOS mirror
# returned on 2026-10-05, so a change in the provider's format shows up here
# rather than as a blank panel in production.
# ---------------------------------------------------------------------------

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.schemas.external_context import ExternalContextState
from app.services import external_context_provider as the_provider
from app.services import external_context_service as the_service


THE_NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


# verbatim from pae-paha.pacioos.hawaii.edu, Tioman, 2026-10-05
THE_LIVE_RESPONSE: str = (
    "time,latitude,longitude,CRW_DHW,CRW_BAA\n"
    "UTC,degrees_north,degrees_east,Celsius weeks,1\n"
    "2026-10-03T12:00:00Z,2.875,104.125,0.0,0\n"
)


# ---------------------------------------------------------------------------
# Adapter — parsing
# ---------------------------------------------------------------------------

def test_the_live_response_parses():
    the_result = the_provider.parse_response(THE_LIVE_RESPONSE, THE_NOW)

    assert the_result.available is True
    assert the_result.grid_latitude == 2.875
    assert the_result.grid_longitude == 104.125

    the_values = {v.context_type_code: v for v in the_result.values}

    assert the_values["degree_heating_week"].numeric_value == 0.0
    assert the_values["degree_heating_week"].display_value == "0.00 °C-weeks"

    assert the_values["bleaching_alert_level"].display_value == "No stress"

    # the day the measurement describes, not the day it was fetched
    assert the_values["degree_heating_week"].represented_date == date(2026, 10, 3)


def test_a_land_or_masked_cell_is_unavailable_not_zero():
    the_masked = THE_LIVE_RESPONSE.replace("0.0,0\n", "-327.68,251\n")

    the_result = the_provider.parse_response(the_masked, THE_NOW)

    assert the_result.available is False
    assert the_result.values == []

    # the cell was still identified, which tells the caller not to retry
    assert the_result.grid_latitude == 2.875


@pytest.mark.parametrize(
    "the_level, the_label",
    [
        (0, "No stress"),
        (1, "Bleaching watch"),
        (2, "Bleaching warning"),
        (3, "Bleaching alert level 1"),
        (4, "Bleaching alert level 2"),
    ],
)
def test_alert_levels_use_noaa_wording(the_level, the_label):
    the_csv = THE_LIVE_RESPONSE.replace("0.0,0\n", f"5.25,{the_level}\n")

    the_result = the_provider.parse_response(the_csv, THE_NOW)
    the_alert = [
        v for v in the_result.values
        if v.context_type_code == "bleaching_alert_level"
    ][0]

    assert the_alert.display_value == the_label


def test_an_unknown_alert_level_is_dropped_rather_than_invented():
    the_csv = THE_LIVE_RESPONSE.replace("0.0,0\n", "3.10,9\n")

    the_result = the_provider.parse_response(the_csv, THE_NOW)

    the_types = {v.context_type_code for v in the_result.values}

    assert the_types == {"degree_heating_week"}


def test_a_response_without_data_rows_is_unavailable():
    the_result = the_provider.parse_response(
        "time,latitude,longitude,CRW_DHW,CRW_BAA\n", THE_NOW
    )

    assert the_result.available is False


def test_sea_surface_temperature_is_never_requested():
    # the easiest value to misread as a safety signal (US8.3 AC3)
    the_url = the_provider.build_request_url("https://example.org/x.csv", 2.88, 104.11)

    assert "CRW_SST" not in the_url
    assert "CRW_DHW" in the_url
    assert "CRW_BAA" in the_url


# ---------------------------------------------------------------------------
# Adapter — mirror fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_second_mirror_is_tried_when_the_first_is_unreachable(monkeypatch):
    monkeypatch.setattr(
        the_provider, "configured_base_urls",
        lambda: ["https://first.example/x.csv", "https://second.example/x.csv"],
    )

    the_calls: list[str] = []

    async def the_fake_mirror(base_url, latitude, longitude):
        the_calls.append(base_url)

        if "first" in base_url:
            return the_provider.ProviderResult(
                available=False, retrieved_at=THE_NOW,
                unavailable_reason="The provider could not be reached",
            )

        return the_provider.parse_response(THE_LIVE_RESPONSE, THE_NOW)

    monkeypatch.setattr(the_provider, "_fetch_from_mirror", the_fake_mirror)

    the_result = await the_provider.fetch_site_context(2.88, 104.11)

    assert the_result.available is True
    assert the_calls == ["https://first.example/x.csv", "https://second.example/x.csv"]


@pytest.mark.asyncio
async def test_a_masked_cell_is_not_retried_on_the_next_mirror(monkeypatch):
    monkeypatch.setattr(
        the_provider, "configured_base_urls",
        lambda: ["https://first.example/x.csv", "https://second.example/x.csv"],
    )

    the_calls: list[str] = []

    async def the_fake_mirror(base_url, latitude, longitude):
        the_calls.append(base_url)
        return the_provider.parse_response(
            THE_LIVE_RESPONSE.replace("0.0,0\n", "-327.68,251\n"), THE_NOW
        )

    monkeypatch.setattr(the_provider, "_fetch_from_mirror", the_fake_mirror)

    the_result = await the_provider.fetch_site_context(2.88, 104.11)

    # both mirrors serve the same product, so asking again cannot help
    assert the_result.available is False
    assert the_calls == ["https://first.example/x.csv"]


# ---------------------------------------------------------------------------
# Service — refresh on read
# ---------------------------------------------------------------------------

def make_stored_row(the_code: str, the_hours_ago: float) -> dict:
    return {
        "context_type_code": the_code,
        "context_type_label": the_code.replace("_", " ").capitalize(),
        "unit": "°C-weeks" if the_code == "degree_heating_week" else None,
        "display_order": 3 if the_code == "degree_heating_week" else 4,
        "numeric_value": 0.0,
        "display_value": "0.00 °C-weeks" if the_code == "degree_heating_week" else "No stress",
        "represented_period_start": date(2026, 10, 3),
        "represented_period_end": date(2026, 10, 3),
        "provider_latitude": 2.875,
        "provider_longitude": 104.125,
        "retrieved_at": THE_NOW - timedelta(hours=the_hours_ago),
        "last_reviewed_at": None,
    }


def patch_site_and_source(monkeypatch, the_has_position: bool = True):
    monkeypatch.setattr(
        the_service.the_repository, "get_site_position",
        AsyncMock(return_value={
            "dive_site_id": 1,
            "site_name": "Tiger Reef",
            "public_area_label": "Tioman Island",
            "centre_latitude": 2.8822 if the_has_position else None,
            "centre_longitude": 104.1087 if the_has_position else None,
        }),
    )
    monkeypatch.setattr(
        the_service.the_repository, "get_source",
        AsyncMock(return_value={
            "external_context_source_id": 1,
            "code": "noaa_crw",
            "name": "NOAA Coral Reef Watch",
            "attribution_text": "Data: NOAA Coral Reef Watch.",
            "provider_url": "https://coralreefwatch.noaa.gov/",
            "licence_note": None,
            "update_cadence": "Daily",
            "is_active": True,
            "last_reviewed_at": None,
        }),
    )
    monkeypatch.setattr(the_service, "utc_now", lambda: THE_NOW)


@pytest.mark.asyncio
async def test_fresh_stored_values_skip_the_provider(monkeypatch):
    patch_site_and_source(monkeypatch)

    monkeypatch.setattr(
        the_service.the_repository, "list_latest_snapshots",
        AsyncMock(return_value=[
            make_stored_row("degree_heating_week", 2),
            make_stored_row("bleaching_alert_level", 2),
        ]),
    )

    the_fetch = AsyncMock()
    monkeypatch.setattr(the_service.the_provider, "fetch_site_context", the_fetch)

    the_response = await the_service.get_external_context(AsyncMock(), 1)

    the_fetch.assert_not_awaited()
    assert the_response.state == ExternalContextState.AVAILABLE
    assert the_response.showing_last_stored_values is False
    assert the_response.attribution


@pytest.mark.asyncio
async def test_stale_values_are_refreshed_and_stored(monkeypatch):
    patch_site_and_source(monkeypatch)

    the_fresh_rows = [
        make_stored_row("degree_heating_week", 0),
        make_stored_row("bleaching_alert_level", 0),
    ]

    monkeypatch.setattr(
        the_service.the_repository, "list_latest_snapshots",
        AsyncMock(side_effect=[
            [make_stored_row("degree_heating_week", 30)],
            the_fresh_rows,
        ]),
    )
    monkeypatch.setattr(
        the_service.the_provider, "fetch_site_context",
        AsyncMock(return_value=the_provider.parse_response(THE_LIVE_RESPONSE, THE_NOW)),
    )

    the_save = AsyncMock(return_value=2)
    monkeypatch.setattr(the_service.the_repository, "save_snapshots", the_save)

    the_db = AsyncMock()
    the_response = await the_service.get_external_context(the_db, 1)

    the_save.assert_awaited_once()
    the_db.commit.assert_awaited_once()

    assert the_response.state == ExternalContextState.AVAILABLE
    assert the_response.showing_last_stored_values is False


@pytest.mark.asyncio
async def test_provider_down_returns_last_stored_values_with_their_dates(monkeypatch):
    patch_site_and_source(monkeypatch)

    the_old_rows = [
        make_stored_row("degree_heating_week", 72),
        make_stored_row("bleaching_alert_level", 72),
    ]

    monkeypatch.setattr(
        the_service.the_repository, "list_latest_snapshots",
        AsyncMock(return_value=the_old_rows),
    )
    monkeypatch.setattr(
        the_service.the_provider, "fetch_site_context",
        AsyncMock(return_value=the_provider.ProviderResult(
            available=False, retrieved_at=THE_NOW,
            unavailable_reason="The provider could not be reached",
        )),
    )

    the_response = await the_service.get_external_context(AsyncMock(), 1)

    # AC4: the page still gets an answer, and says what it is
    assert the_response.state == ExternalContextState.AVAILABLE
    assert the_response.showing_last_stored_values is True
    assert "could not be reached" in the_response.message.lower()

    # the stored dates are reported honestly, not relabelled as current
    assert the_response.items[0].retrieved_at == THE_NOW - timedelta(hours=72)


@pytest.mark.asyncio
async def test_provider_down_with_nothing_stored_is_unavailable(monkeypatch):
    patch_site_and_source(monkeypatch)

    monkeypatch.setattr(
        the_service.the_repository, "list_latest_snapshots",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        the_service.the_provider, "fetch_site_context",
        AsyncMock(return_value=the_provider.ProviderResult(
            available=False, retrieved_at=THE_NOW,
        )),
    )

    the_response = await the_service.get_external_context(AsyncMock(), 1)

    assert the_response.state == ExternalContextState.UNAVAILABLE
    assert the_response.items == []
    assert "everything else on this page is unaffected" in the_response.message.lower()


@pytest.mark.asyncio
async def test_a_caching_failure_does_not_fail_the_request(monkeypatch):
    from sqlalchemy.exc import OperationalError

    patch_site_and_source(monkeypatch)

    monkeypatch.setattr(
        the_service.the_repository, "list_latest_snapshots",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        the_service.the_provider, "fetch_site_context",
        AsyncMock(return_value=the_provider.parse_response(THE_LIVE_RESPONSE, THE_NOW)),
    )
    monkeypatch.setattr(
        the_service.the_repository, "save_snapshots",
        AsyncMock(side_effect=OperationalError("stmt", {}, Exception("db down"))),
    )

    the_db = AsyncMock()
    the_response = await the_service.get_external_context(the_db, 1)

    the_db.rollback.assert_awaited_once()
    assert the_response.state == ExternalContextState.UNAVAILABLE


@pytest.mark.asyncio
async def test_a_site_without_a_position_never_borrows_a_neighbours_value(monkeypatch):
    patch_site_and_source(monkeypatch, the_has_position=False)

    the_fetch = AsyncMock()
    monkeypatch.setattr(the_service.the_provider, "fetch_site_context", the_fetch)

    the_response = await the_service.get_external_context(AsyncMock(), 1)

    the_fetch.assert_not_awaited()
    assert the_response.state == ExternalContextState.SITE_POSITION_UNAVAILABLE


@pytest.mark.asyncio
async def test_unknown_site_is_not_found(monkeypatch):
    monkeypatch.setattr(
        the_service.the_repository, "get_site_position", AsyncMock(return_value=None)
    )

    with pytest.raises(NotFoundError):
        await the_service.get_external_context(AsyncMock(), 999)


def test_the_interpretation_note_makes_no_safety_or_verification_claim():
    from app.schemas.external_context import ExternalContextResponse

    the_note = ExternalContextResponse(
        dive_site_id=1, site_name="x", public_area_label="y",
        state=ExternalContextState.AVAILABLE, message="m",
    ).interpretation_note.lower()

    assert "not a forecast" in the_note
    assert "does not confirm or rule out" in the_note

    for the_word in ("safe", "healthy", "threat-free"):
        assert the_word not in the_note
