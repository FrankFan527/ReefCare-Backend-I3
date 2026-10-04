# ---------------------------------------------------------------------------
# Epic 9 public planning API contracts.
#
# External JSON remains camelCase through APIModel.
#
# Planning assessments describe environmental conditions.
# They must never be interpreted as dive-safety approval.
# ---------------------------------------------------------------------------

from datetime import (
    date,
    datetime,
)
from typing import Literal

from pydantic import (
    Field,
)

from app.core.enums import (
    PlanningBand,
    SeasonalState,
)
from app.schemas.common import (
    APIModel,
)


# ---------------------------------------------------------------------------
# US9.1 Seasonal calendar.
# ---------------------------------------------------------------------------


class SeasonalMonthResponse(APIModel):
    month: int = Field(
        ge=1,
        le=12,
    )

    state: SeasonalState

    headline: str | None = None
    detail: str | None = None


class SeasonalCalendarResponse(APIModel):
    area_code: str

    source: str | None = None
    basis: str | None = None
    reviewed_at: date | None = None

    months: list[
        SeasonalMonthResponse
    ]


# ---------------------------------------------------------------------------
# Shared live forecast signals.
# ---------------------------------------------------------------------------


class PlanningConditionSignals(APIModel):
    wave_height_max_m: float | None = None
    wind_speed_max_kmh: float | None = None

    precipitation_probability_max_pct: (
        float | None
    ) = None


# ---------------------------------------------------------------------------
# US9.2 Date comparison.
# ---------------------------------------------------------------------------


class PlanningBandBreakdown(APIModel):
    more_favourable: int = 0
    mixed: int = 0
    less_favourable: int = 0


class DateComparisonDay(APIModel):
    date: date

    band: PlanningBand

    assessable_sites: int
    total_sites: int

    breakdown: PlanningBandBreakdown

    signals: (
        PlanningConditionSignals
        | None
    ) = None

    reasons: list[str] = Field(
        default_factory=list
    )


class DateComparisonResponse(APIModel):
    area_code: str

    rule_version: str
    source: str

    retrieved_at: datetime | None = None

    days: list[
        DateComparisonDay
    ]


# ---------------------------------------------------------------------------
# US9.3 Site comparison.
# ---------------------------------------------------------------------------


class SiteComparisonItem(APIModel):
    dive_site_id: int
    site_name: str

    band: PlanningBand

    wave_height_max_m: float | None = None
    wind_speed_max_kmh: float | None = None

    precipitation_probability_max_pct: (
        float | None
    ) = None

    reason: str


class SiteComparisonResponse(APIModel):
    area_code: str
    date: date

    rule_version: str
    source: str

    retrieved_at: datetime | None = None

    sites: list[
        SiteComparisonItem
    ]


# ---------------------------------------------------------------------------
# US9.4 AI Planning Brief.
#
# The client supplies intent only:
#
#     siteId
#     plannedDate
#
# It must never supply forecast values or reef facts for
# the AI prompt. The backend resolves those independently.
# ---------------------------------------------------------------------------


class PlanningBriefRequest(APIModel):
    site_id: int = Field(
        gt=0,
    )

    planned_date: date


class PlanningBriefResponse(APIModel):
    site_id: int

    planned_date: date

    status: Literal[
        "generated",
        "unavailable",
    ]

    text: str | None = None

    generated_at: (
        datetime | None
    ) = None