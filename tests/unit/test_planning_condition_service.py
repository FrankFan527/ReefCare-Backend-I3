from app.core.enums import (
    PlanningBand,
)
from app.services.planning_condition_service import (
    aggregate_area_band,
    assess_conditions,
    build_area_reason,
)


def test_more_favourable_when_both_signals_are_within_thresholds():
    result = assess_conditions(
        wave_height_max_m=0.6,
        wind_speed_max_kmh=9.0,
    )

    assert (
        result.band
        == PlanningBand.MORE_FAVOURABLE
    )

    assert result.reasons


def test_more_favourable_includes_exact_upper_boundaries():
    result = assess_conditions(
        wave_height_max_m=0.8,
        wind_speed_max_kmh=12.0,
    )

    assert (
        result.band
        == PlanningBand.MORE_FAVOURABLE
    )


def test_mixed_when_wave_is_between_thresholds():
    result = assess_conditions(
        wave_height_max_m=1.0,
        wind_speed_max_kmh=10.0,
    )

    assert result.band == PlanningBand.MIXED


def test_mixed_when_wind_is_between_thresholds():
    result = assess_conditions(
        wave_height_max_m=0.7,
        wind_speed_max_kmh=15.0,
    )

    assert result.band == PlanningBand.MIXED


def test_less_favourable_when_wave_exceeds_upper_threshold():
    result = assess_conditions(
        wave_height_max_m=1.6,
        wind_speed_max_kmh=8.0,
    )

    assert (
        result.band
        == PlanningBand.LESS_FAVOURABLE
    )


def test_less_favourable_when_wind_exceeds_upper_threshold():
    result = assess_conditions(
        wave_height_max_m=0.5,
        wind_speed_max_kmh=21.0,
    )

    assert (
        result.band
        == PlanningBand.LESS_FAVOURABLE
    )


def test_exact_less_favourable_threshold_is_still_mixed():
    """
    The rule uses "greater than" for the
    less-favourable boundary.

    1.5 m / 20 km/h are therefore not yet classified
    as less favourable.
    """

    result = assess_conditions(
        wave_height_max_m=1.5,
        wind_speed_max_kmh=20.0,
    )

    assert result.band == PlanningBand.MIXED


def test_missing_wave_returns_unavailable():
    result = assess_conditions(
        wave_height_max_m=None,
        wind_speed_max_kmh=10.0,
    )

    assert (
        result.band
        == PlanningBand.UNAVAILABLE
    )


def test_missing_wind_returns_unavailable():
    result = assess_conditions(
        wave_height_max_m=0.5,
        wind_speed_max_kmh=None,
    )

    assert (
        result.band
        == PlanningBand.UNAVAILABLE
    )


def test_missing_both_signals_returns_unavailable():
    result = assess_conditions(
        wave_height_max_m=None,
        wind_speed_max_kmh=None,
    )

    assert (
        result.band
        == PlanningBand.UNAVAILABLE
    )


def test_area_band_uses_least_favourable_assessable_site():
    result = aggregate_area_band(
        [
            PlanningBand.MORE_FAVOURABLE,
            PlanningBand.MIXED,
            PlanningBand.LESS_FAVOURABLE,
        ]
    )

    assert (
        result
        == PlanningBand.LESS_FAVOURABLE
    )


def test_area_band_is_mixed_when_no_less_favourable_site_exists():
    result = aggregate_area_band(
        [
            PlanningBand.MORE_FAVOURABLE,
            PlanningBand.MIXED,
        ]
    )

    assert result == PlanningBand.MIXED


def test_area_band_is_more_favourable_when_all_assessable_sites_are_more_favourable():
    result = aggregate_area_band(
        [
            PlanningBand.MORE_FAVOURABLE,
            PlanningBand.MORE_FAVOURABLE,
        ]
    )

    assert (
        result
        == PlanningBand.MORE_FAVOURABLE
    )


def test_area_band_ignores_non_assessment_states():
    result = aggregate_area_band(
        [
            PlanningBand.NOT_ASSESSABLE,
            PlanningBand.UNAVAILABLE,
            PlanningBand.MORE_FAVOURABLE,
        ]
    )

    assert (
        result
        == PlanningBand.MORE_FAVOURABLE
    )


def test_area_band_is_unavailable_when_nothing_is_assessable():
    result = aggregate_area_band(
        [
            PlanningBand.NOT_ASSESSABLE,
            PlanningBand.UNAVAILABLE,
        ]
    )

    assert (
        result
        == PlanningBand.UNAVAILABLE
    )


def test_area_reason_mentions_assessable_and_total_site_counts():
    reasons = build_area_reason(
        band=PlanningBand.MIXED,
        assessable_sites=3,
        total_sites=4,
    )

    assert len(reasons) == 1

    assert "3" in reasons[0]
    assert "4" in reasons[0]

    assert (
        "least favourable"
        in reasons[0].lower()
    )


def test_unavailable_area_reason_does_not_claim_conditions():
    reasons = build_area_reason(
        band=PlanningBand.UNAVAILABLE,
        assessable_sites=0,
        total_sites=4,
    )

    assert len(reasons) == 1

    assert (
        "no configured site"
        in reasons[0].lower()
    )