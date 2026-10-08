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
from app.schemas.public_context import (
    PublicActivityEntry,
    PublicAssessmentSummary,
    PublicContextState,
    PublicSiteContextResponse,
    PublicThreatSummary,
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


def public_context():
    return PublicSiteContextResponse(
        dive_site_id=23,

        site_name="Mini Mount",

        public_area_label="Tioman Island",

        state=(
            PublicContextState.AVAILABLE
        ),

        message=(
            "ReefCare information for this site covers "
            "1 reviewed threat category and "
            "1 published conservation activity record."
        ),

        assessment_summary=(
            PublicAssessmentSummary(
                accepted_observations=2,
                observations_under_review=1,
            )
        ),

        threats=[
            PublicThreatSummary(
                threat_category_code=(
                    "marine_debris"
                ),

                threat_category_label=(
                    "Marine debris"
                ),

                accepted_report_count=2,

                most_recent_month=(
                    "2026-09"
                ),
            )
        ],

        activity=[
            PublicActivityEntry(
                activity_id=9,

                activity_type=(
                    "debris_cleanup"
                ),

                title=(
                    "Debris collection at Mini Mount"
                ),

                summary=(
                    "Discarded material was collected."
                ),

                activity_date=date(
                    2026,
                    7,
                    24,
                ),

                source_label=(
                    "ReefCare MY demonstration content"
                ),
            )
        ],
    )


def no_public_context():
    return PublicSiteContextResponse(
        dive_site_id=23,

        site_name="Mini Mount",

        public_area_label="Tioman Island",

        state=(
            PublicContextState
            .NO_PUBLIC_CONTEXT
        ),

        message=(
            "No reviewed ReefCare information is "
            "currently available for this site. "
            "This is not a statement about the "
            "condition of the reef."
        ),

        assessment_summary=(
            PublicAssessmentSummary(
                accepted_observations=0,
                observations_under_review=0,
            )
        ),

        threats=[],

        activity=[],
    )


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

    public_context_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "get_public_site_context",
        public_context_mock,
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

    public_context_mock.assert_not_awaited()

    provider_mock.assert_not_awaited()


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

    public_context_mock = AsyncMock()

    monkeypatch.setattr(
        service,
        "get_public_site_context",
        public_context_mock,
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

    public_context_mock.assert_not_awaited()

    provider_mock.assert_not_awaited()


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
        "get_public_site_context",
        AsyncMock(
            return_value=(
                public_context()
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

    assert result.generated_at is None


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
        "get_public_site_context",
        AsyncMock(
            return_value=(
                public_context()
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
                "Reviewed ReefCare context includes "
                "marine debris observations and a "
                "previous debris collection activity."
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
        "marine_debris"
        in provider_input
    )

    assert (
        "acceptedObservations"
        in provider_input
    )

    assert (
        "observationsUnderReview"
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
        "get_public_site_context",
        AsyncMock(
            return_value=(
                public_context()
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


@pytest.mark.asyncio
async def test_no_public_context_is_still_safe_for_ai(
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
        "get_public_site_context",
        AsyncMock(
            return_value=(
                no_public_context()
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
                "No reviewed ReefCare site context "
                "is currently available. Current "
                "planning conditions are described "
                "only by the supplied forecast."
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

    provider_input = (
        captured_payload[
            "input"
        ]
    )

    assert (
        "no_public_context"
        in provider_input
    )

    assert (
        "\"threats\": []"
        in provider_input
    )

    assert (
        "\"activity\": []"
        in provider_input
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

        public_context=(
            public_context()
        ),

        planned_date=(
            PLANNED_DATE
        ),
    )

    encoded = str(
        facts
    ).lower()

    forbidden_terms = [
        "latitude",
        "longitude",
        "observer",
        "observer_id",
        "report_reference",
        "description",
        "file_reference",
        "evidence",
        "claimed_by_user_id",
        "coordinator",
        "decision_note",
        "closure_reason",
    ]

    for term in forbidden_terms:
        assert (
            term
            not in encoded
        )