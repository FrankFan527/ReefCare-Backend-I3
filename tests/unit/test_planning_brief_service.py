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
)
from app.core.exceptions import (
    NotFoundError,
)
from app.schemas.planning import (
    SiteComparisonItem,
    SiteComparisonResponse,
)
from app.services import (
    planning_brief_service
    as service,
)


PLANNED_DATE = date(
    2026,
    10,
    6,
)


def planning_context():
    return {
        "dive_site_id": 23,
        "dive_site_name": "Mini Mount",
        "public_area_label": "Tioman Island",
        "area_code": "tioman",
        "area_label": "Tioman Island",
    }


def site_comparison(
    *,
    band=PlanningBand.MORE_FAVOURABLE,
):
    return SiteComparisonResponse(
        area_code="tioman",

        date=PLANNED_DATE,

        rule_version="i3-draft-1",

        source="Open-Meteo",

        retrieved_at=datetime.fromisoformat(
            "2026-10-04T08:00:00+08:00"
        ),

        sites=[
            SiteComparisonItem(
                dive_site_id=23,

                site_name="Mini Mount",

                band=band,

                wave_height_max_m=(
                    0.6
                    if (
                        band
                        == PlanningBand
                        .MORE_FAVOURABLE
                    )
                    else None
                ),

                wind_speed_max_kmh=(
                    9.0
                    if (
                        band
                        == PlanningBand
                        .MORE_FAVOURABLE
                    )
                    else None
                ),

                precipitation_probability_max_pct=(
                    20.0
                    if (
                        band
                        == PlanningBand
                        .MORE_FAVOURABLE
                    )
                    else None
                ),

                reason="Example rule explanation",
            )
        ],
    )


def public_activity():
    return {
        "dive_site_id": 23,

        "dive_site_name":
            "Mini Mount",

        "public_area_label":
            "Tioman Island",

        "has_activity":
            True,

        "items": [
            {
                "activity_id": 9,
                "activity_type":
                    "debris_cleanup",
                "title":
                    "Debris collection at Mini Mount",
                "summary":
                    "Discarded material was collected.",
                "activity_date":
                    date(
                        2026,
                        7,
                        24,
                    ),
                "source_label":
                    "ReefCare MY demonstration content",
            }
        ],

        "message":
            "Public-safe ReefCare activity is available for this site.",
    }


@pytest.mark.asyncio
async def test_unknown_site_returns_not_found(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=None
        ),
    )

    with pytest.raises(
        NotFoundError,
        match="Dive site not found",
    ):
        await service.generate_planning_brief(
            db=object(),
            site_id=999,
            planned_date=PLANNED_DATE,
        )


@pytest.mark.asyncio
async def test_out_of_horizon_does_not_call_ai(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=(
                planning_context()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "compare_sites_for_date",
        AsyncMock(
            return_value=(
                site_comparison(
                    band=(
                        PlanningBand
                        .OUT_OF_HORIZON
                    )
                )
            )
        ),
    )

    public_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "get_public_activity",
        public_mock,
    )

    provider_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "_post_json",
        provider_mock,
    )

    result = (
        await service
        .generate_planning_brief(
            db=object(),
            site_id=23,
            planned_date=PLANNED_DATE,
        )
    )

    assert (
        result.status
        == "unavailable"
    )

    assert result.text is None
    assert result.generated_at is None

    public_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_assessable_does_not_call_public_context_or_ai(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=(
                planning_context()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "compare_sites_for_date",
        AsyncMock(
            return_value=(
                site_comparison(
                    band=(
                        PlanningBand
                        .NOT_ASSESSABLE
                    )
                )
            )
        ),
    )

    public_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "get_public_activity",
        public_mock,
    )

    result = (
        await service
        .generate_planning_brief(
            db=object(),
            site_id=23,
            planned_date=PLANNED_DATE,
        )
    )

    assert (
        result.status
        == "unavailable"
    )

    public_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_ai_configuration_is_non_blocking(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=(
                planning_context()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "compare_sites_for_date",
        AsyncMock(
            return_value=(
                site_comparison()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "get_public_activity",
        AsyncMock(
            return_value=(
                public_activity()
            )
        ),
    )

    monkeypatch.setattr(
        service.settings,
        "gemini_api_key",
        None,
    )

    result = (
        await service
        .generate_planning_brief(
            db=object(),
            site_id=23,
            planned_date=PLANNED_DATE,
        )
    )

    assert (
        result.status
        == "unavailable"
    )

    assert result.text is None


@pytest.mark.asyncio
async def test_generated_brief_uses_backend_resolved_facts(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=(
                planning_context()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "compare_sites_for_date",
        AsyncMock(
            return_value=(
                site_comparison()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "get_public_activity",
        AsyncMock(
            return_value=(
                public_activity()
            )
        ),
    )

    class FakeSecret:
        def get_secret_value(
            self,
        ):
            return "test-key"

    monkeypatch.setattr(
        service.settings,
        "gemini_api_key",
        FakeSecret(),
    )

    captured_payload = {}

    def fake_post_json(
        payload,
    ):
        captured_payload.update(
            payload
        )

        return {
            "output_text": (
                "Conditions are currently classified "
                "as more favourable under the ReefCare "
                "planning rule.\n\n"
                "A previous public ReefCare activity "
                "record notes debris collection at this "
                "site."
            )
        }

    monkeypatch.setattr(
        service,
        "_post_json",
        fake_post_json,
    )

    result = (
        await service
        .generate_planning_brief(
            db=object(),
            site_id=23,
            planned_date=PLANNED_DATE,
        )
    )

    assert (
        result.status
        == "generated"
    )

    assert result.text is not None

    assert (
        "more favourable"
        in result.text.lower()
    )

    assert (
        result.generated_at
        is not None
    )

    provider_input = (
        captured_payload[
            "input"
        ]
    )

    assert (
        "Mini Mount"
        in provider_input
    )

    assert (
        "debris_cleanup"
        in provider_input
    )

    assert (
        "0.6"
        in provider_input
    )


@pytest.mark.asyncio
async def test_provider_failure_returns_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        service,
        "get_planning_context_for_site",
        AsyncMock(
            return_value=(
                planning_context()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "compare_sites_for_date",
        AsyncMock(
            return_value=(
                site_comparison()
            )
        ),
    )

    monkeypatch.setattr(
        service,
        "get_public_activity",
        AsyncMock(
            return_value=(
                public_activity()
            )
        ),
    )

    class FakeSecret:
        def get_secret_value(
            self,
        ):
            return "test-key"

    monkeypatch.setattr(
        service.settings,
        "gemini_api_key",
        FakeSecret(),
    )

    def failing_provider(
        payload,
    ):
        raise RuntimeError(
            "provider down"
        )

    monkeypatch.setattr(
        service,
        "_post_json",
        failing_provider,
    )

    result = (
        await service
        .generate_planning_brief(
            db=object(),
            site_id=23,
            planned_date=PLANNED_DATE,
        )
    )

    assert (
        result.status
        == "unavailable"
    )

    assert result.text is None

    assert (
        result.generated_at
        is None
    )


def test_prompt_does_not_contain_coordinates_or_private_fields():
    facts = service._build_facts(
        planning_context=(
            planning_context()
        ),

        site_result=(
            site_comparison()
            .sites[0]
        ),

        public_activity=(
            public_activity()
        ),

        planned_date=(
            PLANNED_DATE
        ),
    )

    encoded = str(
        facts
    ).lower()

    assert (
        "latitude"
        not in encoded
    )

    assert (
        "longitude"
        not in encoded
    )

    assert (
        "observer"
        not in encoded
    )

    assert (
        "file_reference"
        not in encoded
    )