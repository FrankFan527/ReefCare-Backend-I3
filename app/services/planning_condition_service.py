# ---------------------------------------------------------------------------
# Epic 9 deterministic planning-condition rules.
#
# No AI or machine-learning model participates in these
# classifications.
#
# Equal inputs under the same rule version must always
# produce the same output.
# ---------------------------------------------------------------------------

from dataclasses import dataclass

from app.core.config import settings
from app.core.enums import (
    PlanningBand,
)


@dataclass(frozen=True)
class ConditionAssessment:
    band: PlanningBand
    reasons: tuple[str, ...]


def assess_conditions(
    *,
    wave_height_max_m: float | None,
    wind_speed_max_kmh: float | None,
) -> ConditionAssessment:
    """
    Convert provider values to the current deterministic
    ReefCare planning band.

    Rainfall remains visible factual context but does not
    affect the draft band until the team approves a
    rainfall rule.

    Missing required inputs produce UNAVAILABLE rather
    than a guessed assessment.
    """

    if (
        wave_height_max_m is None
        or wind_speed_max_kmh is None
    ):
        return ConditionAssessment(
            band=PlanningBand.UNAVAILABLE,
            reasons=(
                (
                    "Required forecast signals "
                    "are unavailable."
                ),
            ),
        )

    if (
        wave_height_max_m
        >
        settings
        .planning_wave_less_favourable_above_m
    ):
        return ConditionAssessment(
            band=(
                PlanningBand
                .LESS_FAVOURABLE
            ),
            reasons=(
                (
                    "Maximum forecast wave height "
                    "exceeds the current "
                    "less-favourable rule threshold."
                ),
            ),
        )

    if (
        wind_speed_max_kmh
        >
        settings
        .planning_wind_less_favourable_above_kmh
    ):
        return ConditionAssessment(
            band=(
                PlanningBand
                .LESS_FAVOURABLE
            ),
            reasons=(
                (
                    "Maximum forecast wind speed "
                    "exceeds the current "
                    "less-favourable rule threshold."
                ),
            ),
        )

    if (
        wave_height_max_m
        <=
        settings
        .planning_wave_more_favourable_max_m
        and
        wind_speed_max_kmh
        <=
        settings
        .planning_wind_more_favourable_max_kmh
    ):
        return ConditionAssessment(
            band=(
                PlanningBand
                .MORE_FAVOURABLE
            ),
            reasons=(
                (
                    "Forecast wave height and wind "
                    "speed are within the current "
                    "more-favourable rule thresholds."
                ),
            ),
        )

    return ConditionAssessment(
        band=PlanningBand.MIXED,
        reasons=(
            (
                "Forecast conditions fall between "
                "the current more-favourable and "
                "less-favourable rule thresholds."
            ),
        ),
    )


def aggregate_area_band(
    site_bands: list[
        PlanningBand
    ],
) -> PlanningBand:
    """
    US9.2 aggregation rule.

    The frontend contract currently defines the area band
    as the least favourable of the assessable sites.

    Missing/unavailable states do not participate because
    they are absence states rather than environmental
    assessments.
    """

    usable = [
        band
        for band in site_bands
        if band in {
            PlanningBand.MORE_FAVOURABLE,
            PlanningBand.MIXED,
            PlanningBand.LESS_FAVOURABLE,
        }
    ]

    if not usable:
        return PlanningBand.UNAVAILABLE

    if (
        PlanningBand.LESS_FAVOURABLE
        in usable
    ):
        return (
            PlanningBand
            .LESS_FAVOURABLE
        )

    if PlanningBand.MIXED in usable:
        return PlanningBand.MIXED

    return (
        PlanningBand
        .MORE_FAVOURABLE
    )


def build_area_reason(
    *,
    band: PlanningBand,
    assessable_sites: int,
    total_sites: int,
) -> list[str]:
    """
    Explain the area-level aggregation without implying
    that ReefCare has made a safety decision.
    """

    if (
        band
        == PlanningBand.UNAVAILABLE
    ):
        return [
            (
                "No configured site had enough "
                "available forecast data for this date."
            )
        ]

    label = {
        PlanningBand.MORE_FAVOURABLE:
            "more favourable",
        PlanningBand.MIXED:
            "mixed",
        PlanningBand.LESS_FAVOURABLE:
            "less favourable",
    }[band]

    return [
        (
            f"The area is classified as {label} "
            f"from {assessable_sites} of "
            f"{total_sites} configured site(s). "
            "The least favourable assessable site "
            "determines the area band."
        )
    ]