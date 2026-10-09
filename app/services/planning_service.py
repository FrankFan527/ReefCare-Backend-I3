# ---------------------------------------------------------------------------
# Epic 9 planning workflow.
#
# Implements the factual/deterministic foundation for:
#
# US9.1 Seasonal Calendar
# US9.2 Travel-Date Comparison
# US9.3 Dive-Site Comparison
#
# Four concepts remain separate:
#
# 1. ReefCare planning reference data
# 2. live provider forecast data
# 3. deterministic ReefCare band rules
# 4. curated seasonal guidance
#
# Historical observations are never presented as a live
# forecast.
# ---------------------------------------------------------------------------

from datetime import (
    date,
    datetime,
    timedelta,
)
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.config import settings
from app.core.enums import (
    PlanningBand,
    SeasonalState,
)
from app.core.exceptions import (
    NotFoundError,
    RequestValidationError,
)
from app.repositories.planning_repository import (
    get_planning_area,
    list_planning_sites,
    list_seasonal_references,
)
from app.schemas.planning import (
    DateComparisonDay,
    DateComparisonResponse,
    PlanningBandBreakdown,
    PlanningConditionSignals,
    SeasonalCalendarResponse,
    SeasonalMonthResponse,
    SiteComparisonItem,
    SiteComparisonResponse,
)
from app.services.planning_condition_service import (
    aggregate_area_band,
    assess_conditions,
    build_area_reason,
)
from app.services.planning_provider_service import (
    PROVIDER_NAME,
    ForecastBatch,
    ForecastSignals,
    fetch_forecast_batch,
)


MAX_TRAVEL_WINDOW_DAYS: int = 14


def _malaysia_timezone() -> ZoneInfo:
    return ZoneInfo(
        settings.planning_timezone
    )


def malaysia_today() -> date:
    return datetime.now(
        _malaysia_timezone()
    ).date()


def forecast_horizon_end() -> date:
    return (
        malaysia_today()
        + timedelta(
            days=(
                settings
                .planning_forecast_horizon_days
                - 1
            )
        )
    )


def date_is_in_forecast_horizon(
    value: date,
) -> bool:
    return (
        malaysia_today()
        <= value
        <= forecast_horizon_end()
    )


async def load_area_or_fail(
    db: AsyncSession,
    area_code: str,
) -> dict:
    area = await get_planning_area(
        db=db,
        area_code=area_code,
    )

    if area is None:
        raise NotFoundError(
            f"Planning area {area_code} not found"
        )

    return area


# ---------------------------------------------------------------------------
# US9.1
# ---------------------------------------------------------------------------


# Reviewed favourability -> public seasonal state.
SEASONAL_STATE_BY_FAVOURABILITY: dict[str, SeasonalState] = {
    "generally_less_favourable": (
        SeasonalState.MONSOON
    ),
    "mixed": (
        SeasonalState.TRANSITION
    ),
    "generally_more_favourable": (
        SeasonalState.TYPICAL
    ),
}


def _unreviewed_month(
    month_number: int,
) -> SeasonalMonthResponse:
    return SeasonalMonthResponse(
        month=month_number,

        state=(
            SeasonalState
            .UNREVIEWED
        ),

        headline=(
            "Reviewed seasonal guidance "
            "unavailable"
        ),

        detail=(
            "ReefCare has not yet published "
            "reviewed seasonal guidance for "
            "this area and month."
        ),
    )


async def get_seasonal_calendar(
    db: AsyncSession,
    area_code: str,
) -> SeasonalCalendarResponse:
    """
    Return twelve explicit month entries.

    Months come from the reviewed seasonal_condition_reference
    rows for the area. A month without a reviewed row, or with
    an unknown favourability, is returned as UNREVIEWED.

    Historical Open-Meteo values are never substituted for
    reviewed seasonal guidance.
    """

    await load_area_or_fail(
        db=db,
        area_code=area_code,
    )

    references = await list_seasonal_references(
        db=db,
        area_code=area_code,
    )

    reference_by_month = {
        reference["calendar_month"]:
            reference

        for reference
        in references
    }

    months = []
    used_references = []

    for month_number in range(1, 13):
        reference = reference_by_month.get(
            month_number
        )

        state = (
            SEASONAL_STATE_BY_FAVOURABILITY.get(
                reference["favourability"]
            )
            if reference is not None
            else None
        )

        if state is None:
            months.append(
                _unreviewed_month(
                    month_number
                )
            )
            continue

        used_references.append(
            reference
        )

        months.append(
            SeasonalMonthResponse(
                month=month_number,
                state=state,
                headline=reference["season_label"],
                detail=reference["typical_conditions"],
            )
        )

    sources = sorted(
        {
            reference["basis_source"]

            for reference
            in used_references
        }
    )

    # The oldest review date applies to the calendar as a whole.
    reviewed_at = min(
        (
            reference["last_reviewed_at"]

            for reference
            in used_references
        ),
        default=None,
    )

    return SeasonalCalendarResponse(
        area_code=area_code,
        source=(
            "; ".join(sources)
            if sources
            else None
        ),
        basis=None,
        reviewed_at=reviewed_at,
        months=months,
    )


# ---------------------------------------------------------------------------
# Shared live forecast helpers.
# ---------------------------------------------------------------------------


def build_provider_positions(
    sites: list[dict],
) -> list[dict]:
    """
    Send only sites that have their own usable position.

    A missing site position is never replaced by another
    site's coordinate or by the area centroid.
    """

    positions = []

    for site in sites:
        latitude = site[
            "centre_latitude"
        ]

        longitude = site[
            "centre_longitude"
        ]

        if (
            latitude is None
            or longitude is None
        ):
            continue

        positions.append(
            {
                "key":
                    site[
                        "dive_site_id"
                    ],

                "latitude":
                    float(latitude),

                "longitude":
                    float(longitude),
            }
        )

    return positions


def get_site_day_result(
    *,
    site: dict,
    requested_date: date,
    batch: ForecastBatch,
) -> tuple[
    PlanningBand,
    ForecastSignals | None,
    list[str],
]:
    """
    Resolve provider values and deterministic assessment
    for one site/date.
    """

    latitude = site[
        "centre_latitude"
    ]

    longitude = site[
        "centre_longitude"
    ]

    if (
        latitude is None
        or longitude is None
    ):
        return (
            PlanningBand.NOT_ASSESSABLE,
            None,
            [
                (
                    "Site position unavailable; "
                    "no neighbouring position was used."
                )
            ],
        )

    if not batch.available:
        return (
            PlanningBand.UNAVAILABLE,
            None,
            [
                (
                    "Forecast provider data is "
                    "currently unavailable."
                )
            ],
        )

    position_forecast = (
        batch.positions.get(
            site[
                "dive_site_id"
            ]
        )
    )

    if position_forecast is None:
        return (
            PlanningBand.UNAVAILABLE,
            None,
            [
                (
                    "No provider result was returned "
                    "for this site position."
                )
            ],
        )

    signals = (
        position_forecast
        .days
        .get(
            requested_date
        )
    )

    if signals is None:
        return (
            PlanningBand.UNAVAILABLE,
            None,
            [
                (
                    "No forecast values were "
                    "returned for this date."
                )
            ],
        )

    assessment = assess_conditions(
        wave_height_max_m=(
            signals
            .wave_height_max_m
        ),

        wind_speed_max_kmh=(
            signals
            .wind_speed_max_kmh
        ),
    )

    return (
        assessment.band,
        signals,
        list(
            assessment.reasons
        ),
    )


def aggregate_signal_maxima(
    signal_rows: list[
        ForecastSignals
    ],
) -> PlanningConditionSignals | None:
    """
    Return a conservative factual summary across the
    assessable sites for a travel date.
    """

    if not signal_rows:
        return None

    waves = [
        row.wave_height_max_m
        for row in signal_rows
        if (
            row.wave_height_max_m
            is not None
        )
    ]

    winds = [
        row.wind_speed_max_kmh
        for row in signal_rows
        if (
            row.wind_speed_max_kmh
            is not None
        )
    ]

    precipitation = [
        row.precipitation_probability_max_pct
        for row in signal_rows
        if (
            row
            .precipitation_probability_max_pct
            is not None
        )
    ]

    return PlanningConditionSignals(
        wave_height_max_m=(
            max(waves)
            if waves
            else None
        ),

        wind_speed_max_kmh=(
            max(winds)
            if winds
            else None
        ),

        precipitation_probability_max_pct=(
            max(precipitation)
            if precipitation
            else None
        ),
    )


# ---------------------------------------------------------------------------
# US9.2
# ---------------------------------------------------------------------------


async def compare_travel_dates(
    db: AsyncSession,
    area_code: str,
    from_date: date,
    to_date: date,
) -> DateComparisonResponse:
    """
    Compare each requested Malaysia calendar date.

    The request may cover at most fourteen days.

    Dates outside ReefCare's live forecast horizon remain
    in the response and are marked OUT_OF_HORIZON.

    Structurally valid but semantically invalid date-window
    input uses the E9 HTTP 422 validation contract.
    """

    area = await load_area_or_fail(
        db=db,
        area_code=area_code,
    )

    if from_date > to_date:
        raise RequestValidationError(
            "from must be on or before to"
        )

    window_days = (
        to_date - from_date
    ).days + 1

    if (
        window_days
        > MAX_TRAVEL_WINDOW_DAYS
    ):
        raise RequestValidationError(
            "The planning date window "
            "cannot exceed 14 days"
        )

    sites = await list_planning_sites(
        db=db,
        area_code=(
            area[
                "area_code"
            ]
        ),
    )

    requested_dates = [
        from_date
        + timedelta(
            days=offset
        )
        for offset in range(
            window_days
        )
    ]

    in_horizon_dates = [
        requested_date
        for requested_date
        in requested_dates
        if date_is_in_forecast_horizon(
            requested_date
        )
    ]

    positions = build_provider_positions(
        sites
    )

    batch: ForecastBatch | None = None

    if (
        in_horizon_dates
        and positions
        and settings
        .planning_forecast_enabled
    ):
        batch = await fetch_forecast_batch(
            positions=positions,

            start_date=min(
                in_horizon_dates
            ),

            end_date=max(
                in_horizon_dates
            ),
        )

    days: list[
        DateComparisonDay
    ] = []

    for requested_date in requested_dates:
        if not date_is_in_forecast_horizon(
            requested_date
        ):
            days.append(
                DateComparisonDay(
                    date=requested_date,

                    band=(
                        PlanningBand
                        .OUT_OF_HORIZON
                    ),

                    assessable_sites=0,

                    total_sites=len(
                        sites
                    ),

                    breakdown=(
                        PlanningBandBreakdown()
                    ),

                    signals=None,

                    reasons=[
                        (
                            "This date is outside "
                            "ReefCare's configured live "
                            "forecast horizon. No live "
                            "forecast assessment was "
                            "inferred or extrapolated."
                        )
                    ],
                )
            )

            continue

        if batch is None:
            days.append(
                DateComparisonDay(
                    date=requested_date,

                    band=(
                        PlanningBand
                        .UNAVAILABLE
                    ),

                    assessable_sites=0,

                    total_sites=len(
                        sites
                    ),

                    breakdown=(
                        PlanningBandBreakdown()
                    ),

                    signals=None,

                    reasons=[
                        (
                            "Live forecast assessment "
                            "is currently unavailable."
                        )
                    ],
                )
            )

            continue

        site_bands: list[
            PlanningBand
        ] = []

        signal_rows: list[
            ForecastSignals
        ] = []

        counts = {
            PlanningBand.MORE_FAVOURABLE:
                0,

            PlanningBand.MIXED:
                0,

            PlanningBand.LESS_FAVOURABLE:
                0,
        }

        for site in sites:
            (
                band,
                signals,
                _,
            ) = get_site_day_result(
                site=site,

                requested_date=(
                    requested_date
                ),

                batch=batch,
            )

            if band in counts:
                counts[
                    band
                ] += 1

                site_bands.append(
                    band
                )

            if signals is not None:
                signal_rows.append(
                    signals
                )

        area_band = aggregate_area_band(
            site_bands
        )

        assessable_sites = sum(
            counts.values()
        )

        reasons = build_area_reason(
            band=area_band,

            assessable_sites=(
                assessable_sites
            ),

            total_sites=len(
                sites
            ),
        )

        days.append(
            DateComparisonDay(
                date=requested_date,

                band=area_band,

                assessable_sites=(
                    assessable_sites
                ),

                total_sites=len(
                    sites
                ),

                breakdown=(
                    PlanningBandBreakdown(
                        more_favourable=(
                            counts[
                                PlanningBand
                                .MORE_FAVOURABLE
                            ]
                        ),

                        mixed=(
                            counts[
                                PlanningBand
                                .MIXED
                            ]
                        ),

                        less_favourable=(
                            counts[
                                PlanningBand
                                .LESS_FAVOURABLE
                            ]
                        ),
                    )
                ),

                signals=(
                    aggregate_signal_maxima(
                        signal_rows
                    )
                ),

                reasons=reasons,
            )
        )

    return DateComparisonResponse(
        area_code=area_code,

        rule_version=(
            settings
            .planning_rule_version
        ),

        source=PROVIDER_NAME,

        retrieved_at=(
            batch.retrieved_at
            if batch is not None
            else None
        ),

        days=days,
    )


# ---------------------------------------------------------------------------
# US9.3
# ---------------------------------------------------------------------------


async def compare_sites_for_date(
    db: AsyncSession,
    area_code: str,
    requested_date: date,
) -> SiteComparisonResponse:
    """
    Compare every configured site in the selected area.

    Missing site positions stay visible as NOT_ASSESSABLE.
    """

    area = await load_area_or_fail(
        db=db,
        area_code=area_code,
    )

    sites = await list_planning_sites(
        db=db,
        area_code=(
            area[
                "area_code"
            ]
        ),
    )

    if not date_is_in_forecast_horizon(
        requested_date
    ):
        return SiteComparisonResponse(
            area_code=area_code,

            date=requested_date,

            rule_version=(
                settings
                .planning_rule_version
            ),

            source=PROVIDER_NAME,

            retrieved_at=None,

            sites=[
                SiteComparisonItem(
                    dive_site_id=(
                        site[
                            "dive_site_id"
                        ]
                    ),

                    site_name=(
                        site[
                            "name"
                        ]
                    ),

                    band=(
                        PlanningBand
                        .OUT_OF_HORIZON
                    ),

                    wave_height_max_m=None,
                    wind_speed_max_kmh=None,

                    precipitation_probability_max_pct=None,

                    reason=(
                        "The selected date is "
                        "outside ReefCare's configured "
                        "live forecast horizon."
                    ),
                )
                for site in sites
            ],
        )

    positions = build_provider_positions(
        sites
    )

    batch: ForecastBatch | None = None

    if (
        positions
        and settings
        .planning_forecast_enabled
    ):
        batch = await fetch_forecast_batch(
            positions=positions,
            start_date=requested_date,
            end_date=requested_date,
        )

    items: list[
        SiteComparisonItem
    ] = []

    for site in sites:
        if (
            site[
                "centre_latitude"
            ] is None
            or
            site[
                "centre_longitude"
            ] is None
        ):
            items.append(
                SiteComparisonItem(
                    dive_site_id=(
                        site[
                            "dive_site_id"
                        ]
                    ),

                    site_name=(
                        site[
                            "name"
                        ]
                    ),

                    band=(
                        PlanningBand
                        .NOT_ASSESSABLE
                    ),

                    wave_height_max_m=None,
                    wind_speed_max_kmh=None,

                    precipitation_probability_max_pct=None,

                    reason=(
                        "Site position unavailable; "
                        "no neighbouring site or area "
                        "centroid was used instead."
                    ),
                )
            )

            continue

        if batch is None:
            items.append(
                SiteComparisonItem(
                    dive_site_id=(
                        site[
                            "dive_site_id"
                        ]
                    ),

                    site_name=(
                        site[
                            "name"
                        ]
                    ),

                    band=(
                        PlanningBand
                        .UNAVAILABLE
                    ),

                    wave_height_max_m=None,
                    wind_speed_max_kmh=None,

                    precipitation_probability_max_pct=None,

                    reason=(
                        "Live forecast assessment "
                        "is currently unavailable."
                    ),
                )
            )

            continue

        (
            band,
            signals,
            reasons,
        ) = get_site_day_result(
            site=site,
            requested_date=requested_date,
            batch=batch,
        )

        items.append(
            SiteComparisonItem(
                dive_site_id=(
                    site[
                        "dive_site_id"
                    ]
                ),

                site_name=(
                    site[
                        "name"
                    ]
                ),

                band=band,

                wave_height_max_m=(
                    signals
                    .wave_height_max_m
                    if (
                        signals
                        is not None
                    )
                    else None
                ),

                wind_speed_max_kmh=(
                    signals
                    .wind_speed_max_kmh
                    if (
                        signals
                        is not None
                    )
                    else None
                ),

                precipitation_probability_max_pct=(
                    signals
                    .precipitation_probability_max_pct
                    if (
                        signals
                        is not None
                    )
                    else None
                ),

                reason=(
                    reasons[0]
                    if reasons
                    else (
                        "No assessment explanation "
                        "is available."
                    )
                ),
            )
        )

    return SiteComparisonResponse(
        area_code=area_code,

        date=requested_date,

        rule_version=(
            settings
            .planning_rule_version
        ),

        source=PROVIDER_NAME,

        retrieved_at=(
            batch.retrieved_at
            if batch is not None
            else None
        ),

        sites=items,
    )