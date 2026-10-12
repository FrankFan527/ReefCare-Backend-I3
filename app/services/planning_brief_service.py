# ---------------------------------------------------------------------------
# US9.4 AI Planning Brief.
#
# The model is a presentation layer over verified backend
# facts. It does not classify conditions, query private
# case information, or make safety decisions.
#
# Flow:
#
# siteId + plannedDate
#       |
#       v
# canonical planning area
#       |
#       v
# US9.3 live site assessment
#       |
#       v
# E8 shared public-safe site context
#       |
#       v
# constrained Gemini summary
#
# AI/provider failure is non-blocking and returns
# status="unavailable" with HTTP 200.
# ---------------------------------------------------------------------------

import asyncio
from datetime import (
    date,
    datetime,
)
import json
from urllib import (
    error,
    request,
)
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.config import settings
from app.core.enums import (
    PlanningBand,
)
from app.core.exceptions import (
    NotFoundError,
)
from app.repositories.planning_brief_repository import (
    get_planning_context_for_site,
)
from app.schemas.planning import (
    PlanningBriefResponse,
)
from app.services.planning_service import (
    compare_sites_for_date,
)
from app.services.public_context_service import (
    get_public_site_context,
)


MAX_PUBLIC_ACTIVITY_ITEMS: int = 5
MAX_PUBLIC_THREAT_ITEMS: int = 5
MAX_BRIEF_LENGTH: int = 3000


BAND_LABELS: dict[PlanningBand, str] = {
    PlanningBand.MORE_FAVOURABLE:
        "More favourable",
    PlanningBand.MIXED:
        "Mixed",
    PlanningBand.LESS_FAVOURABLE:
        "Less favourable",
}

# What each band means for a recreational diver, and the
# planning suggestion ReefCare stands behind. These are
# fixed by the backend so the model cannot soften or
# strengthen them.
BAND_MEANING: dict[PlanningBand, str] = {
    PlanningBand.MORE_FAVOURABLE: (
        "The forecast is generally calm, so the weather "
        "adds little extra difficulty to this dive."
    ),
    PlanningBand.MIXED: (
        "The forecast is not severe, but conditions are "
        "moderate: boat rides, entries, exits and surface "
        "waits may be rougher, which matters most for "
        "newer divers."
    ),
    PlanningBand.LESS_FAVOURABLE: (
        "The forecast is rough, which makes the dive "
        "noticeably harder and raises weather-related "
        "risk, especially at the surface."
    ),
}

BAND_SUGGESTION: dict[PlanningBand, str] = {
    PlanningBand.MORE_FAVOURABLE: (
        "ReefCare suggests this is a good date to plan a "
        "dive here, as long as the site suits your "
        "experience."
    ),
    PlanningBand.MIXED: (
        "ReefCare suggests the dive can still be planned "
        "with caution: it is better suited to divers "
        "comfortable in moderate conditions, and newer "
        "divers may prefer a calmer date."
    ),
    PlanningBand.LESS_FAVOURABLE: (
        "ReefCare suggests choosing another date or site "
        "if you can."
    ),
}

REEF_CONTEXT_PURPOSE: str = (
    "ReefCare shows these records so divers know what has "
    "been reported at this site and what to look out for "
    "underwater. They are past records, not a live survey "
    "of the reef."
)

REPORTING_INVITE: str = (
    "If you spot ghost fishing gear, marine debris, coral "
    "damage or anything unusual on your dive, report it "
    "in ReefCare so it can be reviewed."
)


def _format_number(
    value: float,
) -> str:
    return f"{value:g}"


def _graded_signal(
    *,
    value: float | None,
    unit: str,
    calm_max: float,
    rough_above: float,
    levels: tuple[str, str, str],
) -> dict:
    """
    Place one band-driving signal against the same
    thresholds used by planning_condition_service.
    """

    if value is None:
        return {
            "value": None,
            "level": "unknown",
            "zone": None,
            "affectsBand": True,
        }

    if value <= calm_max:
        level = levels[0]
        zone = "more_favourable"
    elif value <= rough_above:
        level = levels[1]
        zone = "mixed"
    else:
        level = levels[2]
        zone = "less_favourable"

    return {
        "value":
            f"{_format_number(value)} {unit}",

        "level":
            level,

        "zone":
            zone,

        "affectsBand":
            True,

        "thresholds": (
            f"more favourable up to "
            f"{_format_number(calm_max)} {unit}; "
            f"less favourable above "
            f"{_format_number(rough_above)} {unit}"
        ),
    }


def _rain_signal(
    value: float | None,
) -> dict:
    """
    Rainfall stays factual context only. It does not
    change the band until the team approves a rule.
    """

    if value is None:
        return {
            "value": None,
            "level": "unknown",
            "affectsBand": False,
        }

    if value >= 90:
        level = "almost certain"
    elif value >= 60:
        level = "likely"
    elif value >= 30:
        level = "possible"
    else:
        level = "unlikely"

    signal = {
        "value":
            f"{_format_number(value)}%",

        "level":
            level,

        "affectsBand":
            False,
    }

    if value >= 60:
        signal["note"] = (
            "Rain can reduce underwater visibility and "
            "make boat rides and surface waits less "
            "comfortable."
        )

    return signal


def _band_drivers(
    *,
    band: PlanningBand,
    waves: dict,
    wind: dict,
) -> list[str]:
    """
    Name the signal(s) that put the site in its band.
    """

    signals = (
        ("Wave height", waves),
        ("Wind speed", wind),
    )

    def describe(
        name: str,
        signal: dict,
    ) -> str:
        if signal["value"] is None:
            return f"{name} is not available."

        return (
            f"{name} of {signal['value']} is "
            f"{signal['level']} "
            f"({signal['thresholds']})."
        )

    if band == PlanningBand.MORE_FAVOURABLE:
        return [
            describe(name, signal)
            for name, signal in signals
        ]

    drivers = [
        describe(name, signal)
        for name, signal in signals
        if signal["zone"] == band.value
    ]

    others = [
        describe(name, signal)
        for name, signal in signals
        if signal["zone"] != band.value
    ]

    return drivers + others


def _build_guidance(
    site_result,
) -> dict:
    """
    Deterministic plain-language reading of the forecast.

    The model explains this guidance; it does not decide
    it.
    """

    band = site_result.band

    waves = _graded_signal(
        value=site_result.wave_height_max_m,
        unit="m",
        calm_max=(
            settings
            .planning_wave_more_favourable_max_m
        ),
        rough_above=(
            settings
            .planning_wave_less_favourable_above_m
        ),
        levels=(
            "low",
            "moderate",
            "high",
        ),
    )

    wind = _graded_signal(
        value=site_result.wind_speed_max_kmh,
        unit="km/h",
        calm_max=(
            settings
            .planning_wind_more_favourable_max_kmh
        ),
        rough_above=(
            settings
            .planning_wind_less_favourable_above_kmh
        ),
        levels=(
            "light",
            "moderate",
            "strong",
        ),
    )

    return {
        "bandLabel":
            BAND_LABELS[band],

        "bandDrivers":
            _band_drivers(
                band=band,
                waves=waves,
                wind=wind,
            ),

        "signals": {
            "waves":
                waves,

            "wind":
                wind,

            "rain":
                _rain_signal(
                    site_result
                    .precipitation_probability_max_pct
                ),
        },

        "whatThisMeans":
            BAND_MEANING[band],

        "reefCareSuggestion":
            BAND_SUGGESTION[band],

        "reefContextPurpose":
            REEF_CONTEXT_PURPOSE,

        "reportingInvite":
            REPORTING_INVITE,
    }


def _malaysia_now() -> datetime:
    return datetime.now(
        ZoneInfo(
            settings.planning_timezone
        )
    )


def _unavailable_response(
    *,
    site_id: int,
    planned_date: date,
) -> PlanningBriefResponse:
    """
    Build the standard non-blocking fallback response.
    """

    return PlanningBriefResponse(
        site_id=site_id,
        planned_date=planned_date,
        status="unavailable",
        text=None,
        generated_at=None,
    )


def _provider_payload(
    facts: dict,
) -> dict:
    """
    Build a tightly constrained Gemini request.

    All factual input has already been resolved by ReefCare.

    The model may explain those facts but may not add new
    environmental, ecological or safety claims.
    """

    return {
        "model":
            settings.gemini_model,

        "system_instruction": (
            "You write a short ReefCare MY dive-planning "
            "brief that helps a recreational diver decide "
            "whether to plan this dive. Use only the "
            "supplied facts. Never invent weather, sea "
            "conditions, reef condition, wildlife "
            "observations, coordinates, dates, or "
            "conservation activity. "
            "Write exactly three short paragraphs separated "
            "by one blank line, in plain English. "
            "Paragraph 1 starts with \"Why this is "
            "<guidance.bandLabel>:\" and explains the band "
            "from guidance.bandDrivers, quoting the actual "
            "wave height, wind speed and rain chance. Rain "
            "is not part of the band; mention it as a "
            "separate consideration using "
            "guidance.signals.rain. "
            "Paragraph 2 starts with \"What this means:\" "
            "and restates guidance.whatThisMeans and then "
            "guidance.reefCareSuggestion in plain words. "
            "Keep the direction of the suggestion exactly "
            "as given; do not make it more or less "
            "encouraging. Never call the dive safe or "
            "unsafe, never guarantee conditions, and never "
            "give permission or clearance to dive. "
            "Paragraph 3 starts with \"Reef activity:\" "
            "and summarises publicReefContext, then "
            "explains guidance.reefContextPurpose and ends "
            "with guidance.reportingInvite. Public ReefCare "
            "context is historical and must not be "
            "presented as the current condition of the "
            "reef. Accepted observations describe reviewed "
            "ReefCare records, not a complete survey of the "
            "site. Reports still under review must not be "
            "treated as confirmed threats. Threat "
            "categories come only from accepted "
            "observations: state the number under review "
            "as a separate count in its own sentence, and "
            "never attach a threat category, threat type "
            "or the word \"regarding\" to reports under "
            "review. If no public "
            "ReefCare context is available, say so and do "
            "not infer that the reef is healthy, "
            "unaffected, or free of threats. "
            "Do not use headings, bullet points or "
            "markdown, and do not add disclaimers; the "
            "page already shows one."
        ),

        "input":
            json.dumps(
                facts,
                ensure_ascii=False,
                default=str,
            ),

        "response_format": {
            "type": "text",
        },
    }


def _post_json(
    payload: dict,
) -> dict:
    """
    Perform the blocking Gemini request.

    Called only through asyncio.to_thread().

    E9 uses its own Planning Brief timeout because the
    request includes deterministic planning facts together
    with E8 public-safe reef context and may therefore take
    longer than E4 Smart Report requests.
    """

    api_key = (
        settings.gemini_api_key
    )

    if api_key is None:
        raise RuntimeError(
            "AI provider is not configured"
        )

    endpoint = (
        settings
        .gemini_base_url
        .rstrip("/")
        + "/interactions"
    )

    encoded = json.dumps(
        payload
    ).encode(
        "utf-8"
    )

    provider_request = request.Request(
        endpoint,

        data=encoded,

        method="POST",

        headers={
            "x-goog-api-key":
                api_key.get_secret_value(),

            "Content-Type":
                "application/json",
        },
    )

    with request.urlopen(
        provider_request,

        timeout=(
            settings
            .planning_brief_timeout_seconds
        ),

    ) as provider_response:
        return json.loads(
            provider_response
            .read()
            .decode("utf-8")
        )


def _extract_output_text(
    provider_response: dict,
) -> str:
    """
    Support the same Gemini interactions response forms
    already used by Smart Report Structuring.
    """

    direct = (
        provider_response
        .get(
            "output_text"
        )
    )

    if (
        isinstance(
            direct,
            str,
        )
        and direct.strip()
    ):
        return direct.strip()

    for step in (
        provider_response
        .get(
            "steps",
            [],
        )
    ):
        if (
            not isinstance(
                step,
                dict,
            )
            or step.get(
                "type"
            )
            != "model_output"
        ):
            continue

        for content in (
            step.get(
                "content",
                [],
            )
        ):
            if (
                isinstance(
                    content,
                    dict,
                )
                and content.get(
                    "type"
                )
                == "text"
                and isinstance(
                    content.get(
                        "text"
                    ),
                    str,
                )
                and content[
                    "text"
                ].strip()
            ):
                return (
                    content[
                        "text"
                    ]
                    .strip()
                )

    raise ValueError(
        "AI provider returned no text output"
    )


def _normalise_brief_text(
    value: str,
) -> str:
    """
    Keep the provider output compact while preserving the
    blank lines between its paragraphs.
    """

    cleaned = value.strip()

    if not cleaned:
        raise ValueError(
            "AI provider returned an empty brief"
        )

    if (
        len(cleaned)
        > MAX_BRIEF_LENGTH
    ):
        cleaned = (
            cleaned[
                :MAX_BRIEF_LENGTH
            ]
            .rstrip()
        )

    return cleaned


def _build_public_threats(
    public_context,
) -> list[dict]:
    """
    Convert only E8-approved threat summaries into AI facts.

    These summaries contain no report reference, Observer
    identity, evidence, description, precise coordinates,
    Coordinator identity or internal notes.
    """

    return [
        {
            "threatCategoryCode":
                threat.threat_category_code,

            "threatCategoryLabel":
                threat.threat_category_label,

            "acceptedReportCount":
                threat.accepted_report_count,

            "mostRecentMonth":
                threat.most_recent_month,
        }
        for threat
        in public_context.threats[
            :MAX_PUBLIC_THREAT_ITEMS
        ]
    ]


def _build_public_activity(
    public_context,
) -> list[dict]:
    """
    Convert only E8-approved public activity into AI facts.
    """

    return [
        {
            "activityType":
                item.activity_type,

            "title":
                item.title,

            "summary":
                item.summary,

            "activityDate":
                item.activity_date,

            "sourceLabel":
                item.source_label,
        }
        for item
        in public_context.activity[
            :MAX_PUBLIC_ACTIVITY_ITEMS
        ]
    ]


def _build_facts(
    *,
    planning_context,
    site_result,
    public_context,
    planned_date: date,
) -> dict:
    """
    Construct the only facts Gemini is allowed to use.

    E8 is the single authority for ReefCare public-safe
    site context.

    No coordinates, Observer identity, private reports,
    evidence files, report descriptions, Coordinator
    identity, internal notes or restricted case information
    enter the prompt.
    """

    public_threats = (
        _build_public_threats(
            public_context
        )
    )

    public_activity = (
        _build_public_activity(
            public_context
        )
    )

    return {
        "site": {
            "diveSiteId":
                planning_context[
                    "dive_site_id"
                ],

            "name":
                planning_context[
                    "dive_site_name"
                ],

            "areaCode":
                planning_context[
                    "area_code"
                ],

            "areaLabel":
                planning_context[
                    "area_label"
                ],
        },

        "plannedDate":
            planned_date,

        "conditions": {
            "band":
                site_result.band.value,

            "waveHeightMaxM":
                site_result
                .wave_height_max_m,

            "windSpeedMaxKmh":
                site_result
                .wind_speed_max_kmh,

            "precipitationProbabilityMaxPct":
                site_result
                .precipitation_probability_max_pct,

            "ruleExplanation":
                site_result.reason,
        },

        "guidance":
            _build_guidance(
                site_result
            ),

        "publicReefContext": {
            "state":
                public_context
                .state
                .value,

            "message":
                public_context
                .message,

            "assessmentSummary": {
                "acceptedObservations":
                    public_context
                    .assessment_summary
                    .accepted_observations,

                "observationsUnderReview":
                    public_context
                    .assessment_summary
                    .observations_under_review,
            },

            "threats":
                public_threats,

            "activity":
                public_activity,
        },
    }


async def generate_planning_brief(
    *,
    db: AsyncSession,
    site_id: int,
    planned_date: date,
) -> PlanningBriefResponse:
    """
    Generate one optional public planning brief.

    The request contains only site/date intent.

    All factual content is independently retrieved by the
    backend.

    Environmental facts come from US9.3 deterministic/live
    planning assessment.

    ReefCare history/context comes only from the shared E8
    public-safe boundary.

    Missing/out-of-horizon conditions and any Gemini
    provider failure return the normal unavailable shape,
    not HTTP 500.
    """

    planning_context = (
        await get_planning_context_for_site(
            db=db,
            dive_site_id=site_id,
        )
    )

    if planning_context is None:
        raise NotFoundError(
            "Dive site not found"
        )

    site_comparison = (
        await compare_sites_for_date(
            db=db,

            area_code=(
                planning_context[
                    "area_code"
                ]
            ),

            requested_date=(
                planned_date
            ),
        )
    )

    selected_site = next(
        (
            item
            for item
            in site_comparison.sites
            if (
                item.dive_site_id
                == site_id
            )
        ),
        None,
    )

    if selected_site is None:
        return _unavailable_response(
            site_id=site_id,
            planned_date=planned_date,
        )

    # No AI prose is generated when ReefCare itself has no
    # factual environmental assessment to summarise.
    if selected_site.band in {
        PlanningBand.UNAVAILABLE,
        PlanningBand.OUT_OF_HORIZON,
        PlanningBand.NOT_ASSESSABLE,
    }:
        return _unavailable_response(
            site_id=site_id,
            planned_date=planned_date,
        )

    # E8 is the single source of public-safe ReefCare site
    # context used by both E2 and E9.
    #
    # This service already applies all publication and
    # privacy eligibility rules before anything reaches the
    # Planning Brief prompt.
    public_context = (
        await get_public_site_context(
            db=db,
            dive_site_id=site_id,
        )
    )

    facts = _build_facts(
        planning_context=(
            planning_context
        ),

        site_result=(
            selected_site
        ),

        public_context=(
            public_context
        ),

        planned_date=(
            planned_date
        ),
    )

    if (
        settings.gemini_api_key
        is None
    ):
        return _unavailable_response(
            site_id=site_id,
            planned_date=planned_date,
        )

    try:
        provider_response = (
            await asyncio.wait_for(
                asyncio.to_thread(
                    _post_json,
                    _provider_payload(
                        facts
                    ),
                ),

                timeout=(
                    settings
                    .planning_brief_timeout_seconds
                    + 2
                ),
            )
        )

        brief_text = (
            _normalise_brief_text(
                _extract_output_text(
                    provider_response
                )
            )
        )

        return PlanningBriefResponse(
            site_id=site_id,

            planned_date=(
                planned_date
            ),

            status="generated",

            text=brief_text,

            generated_at=(
                _malaysia_now()
            ),
        )

    except (
        TimeoutError,
        error.HTTPError,
        error.URLError,
        json.JSONDecodeError,
        ValueError,
        RuntimeError,
        OSError,
    ):
        return _unavailable_response(
            site_id=site_id,
            planned_date=planned_date,
        )