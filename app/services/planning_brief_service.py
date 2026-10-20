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
# constrained DeepSeek summary
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


BAND_LABELS: dict[
    PlanningBand,
    str,
] = {
    PlanningBand.MORE_FAVOURABLE:
        "More favourable",

    PlanningBand.MIXED:
        "Mixed",

    PlanningBand.LESS_FAVOURABLE:
        "Less favourable",
}


# ---------------------------------------------------------------------------
# Deterministic planning meaning.
#
# These statements are fixed by the backend. The AI may
# restate them in simpler language but must not change the
# direction of the guidance.
# ---------------------------------------------------------------------------

BAND_MEANING: dict[
    PlanningBand,
    str,
] = {
    PlanningBand.MORE_FAVOURABLE: (
        "Wave and wind conditions are relatively calm "
        "for planning this dive."
    ),

    PlanningBand.MIXED: (
        "Wave or wind conditions are moderate, so this "
        "dive may need more careful planning."
    ),

    PlanningBand.LESS_FAVOURABLE: (
        "Wave or wind conditions are rougher, making "
        "this date less favourable for planning."
    ),
}


BAND_SUGGESTION: dict[
    PlanningBand,
    str,
] = {
    PlanningBand.MORE_FAVOURABLE: (
        "ReefCare suggests this is a more favourable "
        "date to plan the dive, while still considering "
        "the separate rain information and whether the "
        "site suits the diver's experience."
    ),

    PlanningBand.MIXED: (
        "ReefCare suggests planning with caution. "
        "Divers who are less comfortable in moderate "
        "conditions may prefer a calmer date."
    ),

    PlanningBand.LESS_FAVOURABLE: (
        "ReefCare suggests considering another date "
        "or site if possible."
    ),
}


REEF_CONTEXT_PURPOSE: str = (
    "These are historical ReefCare records that help "
    "divers understand what has previously been reported "
    "at the site. They are not a live survey or statement "
    "of the reef's current condition."
)


REPORTING_INVITE: str = (
    "If you notice ghost fishing gear, marine debris, "
    "coral damage or anything unusual during the dive, "
    "you can report it in ReefCare for review."
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
    levels: tuple[
        str,
        str,
        str,
    ],
) -> dict:
    """
    Classify one band-driving signal using the same
    thresholds as planning_condition_service.

    Threshold values remain internal. They are used to
    determine the signal zone but are deliberately not
    exposed as prose facts to the AI, because the public
    Planning Brief should explain the current result rather
    than reproduce ReefCare's internal rule table.
    """

    if value is None:
        return {
            "value":
                None,

            "level":
                "unknown",

            "zone":
                None,

            "affectsBand":
                True,
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
    }


def _rain_signal(
    value: float | None,
) -> dict:
    """
    Rainfall stays factual context only.

    Rain does not change the deterministic planning band
    until ReefCare explicitly adopts a rain-based rule.
    """

    if value is None:
        return {
            "value":
                None,

            "level":
                "unknown",

            "affectsBand":
                False,
        }

    if value >= 90:
        level = "very high"

    elif value >= 60:
        level = "high"

    elif value >= 30:
        level = "moderate"

    else:
        level = "low"

    return {
        "value":
            f"{_format_number(value)}%",

        "level":
            level,

        "affectsBand":
            False,
    }


def _band_drivers(
    *,
    band: PlanningBand,
    waves: dict,
    wind: dict,
) -> list[str]:
    """
    Describe the current band-driving signals without
    repeating the complete threshold table.

    This keeps the public AI brief concise and avoids
    apparently contradictory wording such as explaining a
    More favourable result while also repeating a
    "less favourable above ..." rule.
    """

    signals = (
        (
            "Wave height",
            waves,
        ),
        (
            "Wind speed",
            wind,
        ),
    )

    def describe(
        name: str,
        signal: dict,
    ) -> str:
        if (
            signal[
                "value"
            ]
            is None
        ):
            return (
                f"{name} is unavailable."
            )

        return (
            f"{name} is "
            f"{signal['value']} "
            f"and is rated "
            f"{signal['level']}."
        )

    if (
        band
        == PlanningBand.MORE_FAVOURABLE
    ):
        return [
            describe(
                name,
                signal,
            )
            for (
                name,
                signal,
            )
            in signals
        ]

    drivers = [
        describe(
            name,
            signal,
        )

        for (
            name,
            signal,
        )
        in signals

        if (
            signal[
                "zone"
            ]
            == band.value
        )
    ]

    others = [
        describe(
            name,
            signal,
        )

        for (
            name,
            signal,
        )
        in signals

        if (
            signal[
                "zone"
            ]
            != band.value
        )
    ]

    return (
        drivers
        + others
    )


def _build_guidance(
    site_result,
) -> dict:
    """
    Build deterministic plain-language guidance.

    The AI explains this guidance; it does not decide or
    recalculate the planning band.
    """

    band = (
        site_result.band
    )

    waves = _graded_signal(
        value=(
            site_result
            .wave_height_max_m
        ),

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
        value=(
            site_result
            .wind_speed_max_kmh
        ),

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
            BAND_LABELS[
                band
            ],

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
            BAND_MEANING[
                band
            ],

        "reefCareSuggestion":
            BAND_SUGGESTION[
                band
            ],

        "reefContextPurpose":
            REEF_CONTEXT_PURPOSE,

        "reportingInvite":
            REPORTING_INVITE,
    }


def _malaysia_now() -> datetime:
    return datetime.now(
        ZoneInfo(
            settings
            .planning_timezone
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

        planned_date=(
            planned_date
        ),

        status=(
            "unavailable"
        ),

        text=None,

        generated_at=None,
    )


def _provider_payload(
    facts: dict,
) -> dict:
    """
    Build a tightly constrained DeepSeek request.

    All factual input has already been resolved by ReefCare.

    The model may explain those facts but may not add new
    environmental, ecological or safety claims.
    """

    return {
        "model":
            settings
            .deepseek_model,

        "messages": [
            {
                "role":
                    "system",

                "content": (
                    "You write a short ReefCare MY "
                    "dive-planning brief for a "
                    "recreational diver. "

                    "Use only the supplied facts. "
                    "Never invent weather, sea "
                    "conditions, reef condition, "
                    "wildlife observations, coordinates, "
                    "dates, conservation activity, "
                    "threats or safety conclusions. "

                    "The planning band has already been "
                    "calculated by ReefCare's deterministic "
                    "backend rules. Do not recalculate it, "
                    "question it or introduce another band. "

                    "Write exactly three short paragraphs "
                    "separated by one blank line. "
                    "Use clear, natural English suitable "
                    "for a public website. Keep the whole "
                    "brief concise. "

                    "Paragraph 1 must start with "
                    "\"Why this is "
                    "<guidance.bandLabel>:\". "
                    "Briefly explain the selected band "
                    "using guidance.bandDrivers and the "
                    "actual wave and wind values. "
                    "Do not repeat threshold ranges, "
                    "internal rule boundaries, or phrases "
                    "such as \"more favourable up to\" or "
                    "\"less favourable above\". "
                    "Do not put technical rule explanations "
                    "inside brackets or parentheses. "

                    "Mention rain once only as a separate "
                    "consideration. Use the actual rain "
                    "chance and its simple level from "
                    "guidance.signals.rain. "
                    "Do not imply that rain changes the "
                    "planning band. "
                    "For example, say that rain chance is "
                    "high and should be considered "
                    "separately. Do not explain internal "
                    "rain classification rules. "

                    "Paragraph 2 must start with "
                    "\"What this means:\". "
                    "Explain guidance.whatThisMeans and "
                    "guidance.reefCareSuggestion in simple "
                    "practical language. "
                    "Keep the direction of the suggestion "
                    "exactly as supplied. "
                    "Do not contradict the selected band. "
                    "Never call the dive safe or unsafe. "
                    "Never guarantee conditions, give "
                    "permission, approval or clearance to "
                    "dive. "

                    "Paragraph 3 must start with "
                    "\"Reef activity:\". "
                    "Summarise only the most relevant "
                    "publicReefContext. "
                    "Keep this paragraph concise. "

                    "Threat categories may come only from "
                    "accepted observations. "
                    "Reports still under review must be "
                    "reported only as a separate count and "
                    "must not be treated as confirmed "
                    "threats. "
                    "Never attach a threat category, threat "
                    "type, or the word \"regarding\" to "
                    "reports under review. "

                    "If there is no reviewed public "
                    "ReefCare information, simply say that "
                    "no reviewed ReefCare information is "
                    "currently available for the site. "
                    "Do not infer that the reef is healthy, "
                    "unaffected or free of threats. "

                    "Make clear in one short sentence that "
                    "the ReefCare records are historical "
                    "context and not the reef's current "
                    "condition. "
                    "End with a short version of "
                    "guidance.reportingInvite. "

                    "Do not reproduce database field names, "
                    "internal codes, ruleExplanation, "
                    "threshold tables or configuration "
                    "values. "

                    "Do not use markdown headings, bullet "
                    "points, numbered lists or additional "
                    "sections. "
                    "The required paragraph starters are "
                    "plain text labels, not markdown "
                    "headings. "

                    "Do not add a disclaimer because the "
                    "page already displays one."
                ),
            },
            {
                "role":
                    "user",

                "content":
                    json.dumps(
                        facts,
                        ensure_ascii=False,
                        default=str,
                    ),
            },
        ],

        "thinking": {
            "type":
                "disabled",
        },

        "max_tokens":
            520,

        "temperature":
            0.2,
    }


def _post_json(
    payload: dict,
) -> dict:
    """
    Perform the blocking DeepSeek request.

    Called only through asyncio.to_thread().

    E9 uses its own Planning Brief timeout because the
    request includes deterministic planning facts together
    with E8 public-safe reef context and may therefore take
    longer than E4 Smart Report requests.
    """

    api_key = (
        settings
        .deepseek_api_key
    )

    if api_key is None:
        raise RuntimeError(
            "AI provider is not configured"
        )

    endpoint = (
        settings
        .deepseek_base_url
        .rstrip("/")
        + "/chat/completions"
    )

    encoded = (
        json.dumps(
            payload
        )
        .encode(
            "utf-8"
        )
    )

    provider_request = (
        request.Request(
            endpoint,

            data=encoded,

            method="POST",

            headers={
                "Authorization":
                    (
                        "Bearer "
                        + api_key
                        .get_secret_value()
                    ),

                "Content-Type":
                    "application/json",
            },
        )
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
            .decode(
                "utf-8"
            )
        )


def _extract_output_text(
    provider_response: dict,
) -> str:
    """
    Read the text from a DeepSeek chat completion.
    """

    choices = (
        provider_response
        .get(
            "choices"
        )
    )

    if (
        isinstance(
            choices,
            list,
        )
        and choices
    ):
        choice = (
            choices[0]
        )

        if isinstance(
            choice,
            dict,
        ):
            message = (
                choice.get(
                    "message"
                )
            )

            if isinstance(
                message,
                dict,
            ):
                content = (
                    message.get(
                        "content"
                    )
                )

                if (
                    isinstance(
                        content,
                        str,
                    )
                    and content.strip()
                ):
                    return (
                        content.strip()
                    )

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
        return (
            direct.strip()
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

    cleaned = (
        value.strip()
    )

    if not cleaned:
        raise ValueError(
            "AI provider returned an empty brief"
        )

    if (
        len(
            cleaned
        )
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
                threat
                .threat_category_code,

            "threatCategoryLabel":
                threat
                .threat_category_label,

            "acceptedReportCount":
                threat
                .accepted_report_count,

            "mostRecentMonth":
                threat
                .most_recent_month,
        }

        for threat
        in (
            public_context
            .threats[
                :MAX_PUBLIC_THREAT_ITEMS
            ]
        )
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
                item
                .activity_type,

            "title":
                item
                .title,

            "summary":
                item
                .summary,

            "activityDate":
                item
                .activity_date,

            "sourceLabel":
                item
                .source_label,
        }

        for item
        in (
            public_context
            .activity[
                :MAX_PUBLIC_ACTIVITY_ITEMS
            ]
        )
    ]


def _build_facts(
    *,
    planning_context,
    site_result,
    public_context,
    planned_date: date,
) -> dict:
    """
    Construct the only facts the AI provider is allowed to use.

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
                site_result
                .band
                .value,

            "waveHeightMaxM":
                site_result
                .wave_height_max_m,

            "windSpeedMaxKmh":
                site_result
                .wind_speed_max_kmh,

            "precipitationProbabilityMaxPct":
                site_result
                .precipitation_probability_max_pct,

            # This deterministic explanation is retained for
            # backend traceability. The prompt explicitly
            # forbids the model from reproducing internal rule
            # language or threshold tables.
            "ruleExplanation":
                site_result
                .reason,
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

    Missing/out-of-horizon conditions and any AI provider
    failure return the normal unavailable shape, not HTTP
    500.
    """

    planning_context = (
        await (
            get_planning_context_for_site(
                db=db,

                dive_site_id=(
                    site_id
                ),
            )
        )
    )

    if (
        planning_context
        is None
    ):
        raise NotFoundError(
            "Dive site not found"
        )

    site_comparison = (
        await (
            compare_sites_for_date(
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
    )

    selected_site = next(
        (
            item

            for item
            in (
                site_comparison
                .sites
            )

            if (
                item
                .dive_site_id
                == site_id
            )
        ),
        None,
    )

    if (
        selected_site
        is None
    ):
        return (
            _unavailable_response(
                site_id=site_id,

                planned_date=(
                    planned_date
                ),
            )
        )

    # No AI prose is generated when ReefCare itself has no
    # factual environmental assessment to summarise.
    if (
        selected_site.band
        in {
            PlanningBand.UNAVAILABLE,
            PlanningBand.OUT_OF_HORIZON,
            PlanningBand.NOT_ASSESSABLE,
        }
    ):
        return (
            _unavailable_response(
                site_id=site_id,

                planned_date=(
                    planned_date
                ),
            )
        )

    # E8 is the single source of public-safe ReefCare site
    # context used by both E2 and E9.
    #
    # This service already applies all publication and
    # privacy eligibility rules before anything reaches the
    # Planning Brief prompt.
    public_context = (
        await (
            get_public_site_context(
                db=db,

                dive_site_id=(
                    site_id
                ),
            )
        )
    )

    facts = (
        _build_facts(
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
    )

    if (
        settings
        .deepseek_api_key
        is None
    ):
        return (
            _unavailable_response(
                site_id=site_id,

                planned_date=(
                    planned_date
                ),
            )
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
            site_id=(
                site_id
            ),

            planned_date=(
                planned_date
            ),

            status=(
                "generated"
            ),

            text=(
                brief_text
            ),

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
        return (
            _unavailable_response(
                site_id=site_id,

                planned_date=(
                    planned_date
                ),
            )
        )