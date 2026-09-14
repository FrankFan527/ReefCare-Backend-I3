"""US5.6 report aggregation, generalised map projection and safe navigation."""

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.exceptions import NotFoundError, ServiceError
from app.repositories import hotspot_repository as repository
from app.schemas.hotspot import (
    FrequencyBucket, GeneralisedMapLocation, HotspotAnalysisResponse,
    HotspotContextResponse, HotspotFilters, HotspotIntakeItem,
    HotspotOptionsResponse, HotspotQuality, HotspotQuery,
    HotspotReportsResponse, HotspotSite, HotspotSiteSummary,
    HotspotSummary, ThreatCount, ThreatOption,
)


logger = logging.getLogger(__name__)
MALAYSIA = ZoneInfo("Asia/Kuala_Lumpur")
THREATS = {
    "ghost_gear": "Ghost fishing gear",
    "coral_bleaching": "Coral bleaching",
    "marine_debris": "Marine debris",
    "physical_damage": "Physical reef damage",
    "unsure": "Unsure",
}
UNAVAILABLE = "Geographic analysis is unavailable. The queue and normal case review remain accessible."


class AnalysisUnavailable(ServiceError):
    status_code = 503
    error_code = "analysis_unavailable"
    default_message = UNAVAILABLE

    def __init__(self):
        super().__init__(headers={"Cache-Control": "private, no-store", "Retry-After": "30"})


def resolve_filters(query: HotspotQuery, today: date | None = None) -> HotspotFilters:
    today = today or datetime.now(MALAYSIA).date()
    return HotspotFilters(
        site_id=query.site_id, area=query.area, region=query.region, threat=query.threat,
        observed_from=query.observed_from or today - timedelta(days=29),
        observed_to=query.observed_to or today, interval=query.interval,
    )


def site_projection(row) -> HotspotSite | None:
    if row["site_id"] is None or not (row["site_name"] or "").strip():
        return None
    return HotspotSite(
        site_id=row["site_id"], name=row["site_name"],
        area=row["area"], region=row["region"],
    )


def site_map_projection(
    row,
) -> GeneralisedMapLocation | None:
    """
    Build a privacy-safe map anchor from the report's
    named dive-site reference.

    The repository has already rounded the canonical
    dive-site centre to two decimal places.

    This function never reads or uses report_location
    coordinates.
    """

    latitude = row.get(
        "map_latitude"
    )

    longitude = row.get(
        "map_longitude"
    )

    if (
        latitude is None
        or longitude is None
    ):
        return None

    uncertainty_metres = max(
        int(
            row.get(
                "map_uncertainty_metres"
            )
            or 1000
        ),
        1000,
    )

    return GeneralisedMapLocation(
        latitude=float(
            latitude
        ),

        longitude=float(
            longitude
        ),

        uncertainty_metres=(
            uncertainty_metres
        ),

        basis=(
            "Generalised named dive-site reference "
            "centre derived from the report's dive "
            "session; rounded to 2 decimal places "
            "and not an incident location."
        ),
    )


async def query_safely(db, function, **kwargs):
    if not settings.hotspot_enabled:
        raise AnalysisUnavailable()
    try:
        async with asyncio.timeout(settings.hotspot_timeout_seconds):
            return await function(db=db, **kwargs)
    except (SQLAlchemyError, TimeoutError) as exc:
        # This read-only endpoint owns the session; no workflow writes occur.
        try:
            async with asyncio.timeout(2):
                await db.rollback()
        except (SQLAlchemyError, TimeoutError):
            logger.warning("US5.6 failed session cleanup; session will be closed")
        logger.warning("US5.6 query unavailable (%s)", type(exc).__name__)
        raise AnalysisUnavailable() from exc


def bucket_start(value: date, interval: str) -> date:
    if interval == "week":
        return value - timedelta(days=value.weekday())
    if interval == "month":
        return value.replace(day=1)
    return value


def next_bucket(value: date, interval: str) -> date:
    if interval == "month":
        if value.month == 12:
            return date(value.year + 1, 1, 1)
        return date(value.year, value.month + 1, 1)
    return value + timedelta(days=7 if interval == "week" else 1)


def build_summary(groups: list, filters: HotspotFilters) -> HotspotSummary:
    threats = Counter({code: 0 for code in THREATS})
    labels = dict(THREATS)
    frequency = Counter()
    for row in groups:
        threats[row["threat_code"]] += row["report_count"]
        labels.setdefault(row["threat_code"], row["threat_label"])
        value = row["bucket"]
        frequency[date.fromisoformat(value) if isinstance(value, str) else value] += row["report_count"]

    buckets = []
    current = bucket_start(filters.observed_from, filters.interval)
    end = filters.observed_to + timedelta(days=1)
    while current < end:
        following = next_bucket(current, filters.interval)
        included_from, included_end = max(current, filters.observed_from), min(following, end)
        buckets.append(FrequencyBucket(
            bucket_start=current, bucket_end_exclusive=following,
            included_from=included_from, included_to=included_end - timedelta(days=1),
            is_partial=(included_from != current or included_end != following),
            report_count=frequency[current],
        ))
        current = following
    # Conservative display rule, not a statistical significance/risk claim.
    has_history = sum(count > 0 for count in frequency.values()) >= 2

    return HotspotSummary(
        report_count=sum(threats.values()),
        threat_breakdown=[ThreatCount(code=code, label=labels[code], report_count=count)
                          for code, count in threats.items()],
        frequency=buckets,
        trend_state="available" if has_history else "insufficient_history",
        trend_message=(
            "Counts are available in at least two observation intervals; partial intervals are labelled."
            if has_history else
            "A trend cannot be shown: reports occur in fewer than two observation intervals."
        ),
    )


async def get_options(db) -> HotspotOptionsResponse:
    defaults = resolve_filters(HotspotQuery())
    try:
        rows = await query_safely(db, repository.list_sites)
    except AnalysisUnavailable:
        return HotspotOptionsResponse(state="unavailable", message=UNAVAILABLE, default_filters=defaults)
    return HotspotOptionsResponse(
        state="ready", message="Select named sites, area/region labels, threat and observation period.",
        sites=[site_projection(row) for row in rows],
        threats=[ThreatOption(code=code, label=label) for code, label in THREATS.items()],
        default_filters=defaults,
    )


async def get_analysis(db, query: HotspotQuery) -> HotspotAnalysisResponse:
    filters = resolve_filters(query)
    try:
        data = await query_safely(db, repository.get_analysis, filters=filters)
    except AnalysisUnavailable:
        return HotspotAnalysisResponse(
            state="unavailable", message=UNAVAILABLE, filters=filters,
            map_state="unavailable", map_message=UNAVAILABLE,
        )

    groups = data["groups"]
    summary = build_summary(groups, filters)
    site_groups = {}
    for row in groups:
        site_groups.setdefault(row["site_id"], []).append(row)
    sites = [HotspotSiteSummary(
        **build_summary(rows, filters).model_dump(by_alias=False),
        site=site_projection(rows[0]), map_location=site_map_projection(rows[0]),
    ) for site_id, rows in site_groups.items()]
    sites.sort(key=lambda item: (-item.report_count, item.site.site_id))
    included = data["included_report_count"]
    matching = data["matching_report_count"]
    mapped = sum(site.report_count for site in sites if site.map_location is not None)

    if included:
        state, message = "ready", "Reporting counts are available for the selected named sites and period."
    elif matching or data["undated_report_count"]:
        state, message = "insufficient_data", "Reports exist, but none can be assigned to a usable named site and the selected observation period."
    else:
        state, message = "no_matches", "No reports match these filters. This does not establish absence of reef threats."
    if state == "no_matches":
        map_state, map_message = "no_matches", message
    elif mapped == 0:
        map_state, map_message = "insufficient_data", "No named dive sites in this selection have usable reference-centre coordinates. Use named-site summaries."
    elif mapped < included:
        map_state, map_message = "partial", "Only reports at named sites with usable reference-centre coordinates are plotted."
    else:
        map_state, map_message = "ready", "Markers represent generalised named sites, not underwater incident points."
    return HotspotAnalysisResponse(
        state=state, message=message, filters=filters,
        last_successful_update_at=data["analysed_at"], summary=summary, sites=sites,
        data_quality=HotspotQuality(
            matching_report_count=matching, included_report_count=included,
            excluded_missing_site_count=matching - included,
            undated_report_count=data["undated_report_count"],
            mapped_report_count=mapped, unmapped_report_count=included - mapped,
        ), map_state=map_state, map_message=map_message,
    )


def project_intake(row, coordinator_id: int) -> HotspotIntakeItem:
    owner = row["claimed_by_user_id"]
    ownership = "unclaimed" if owner is None else "mine" if owner == coordinator_id else "other"
    if ownership == "mine":
        action = "review"
    elif ownership == "other":
        action = "assigned_summary"
    elif row["is_closed"]:
        action = "restricted_summary"
    else:
        action = "claim"
    path = f"{settings.api_v1_prefix}/coordinator/reports/{quote(row['report_reference'], safe='')}"
    return HotspotIntakeItem(
        report_reference=row["report_reference"], site=site_projection(row),
        threat=row["threat_label"], threat_code=row["threat_code"],
        observed_at=row["observed_at"], submitted_at=row["submitted_at"],
        status_code=row["status_code"], status_label=row["status_label"],
        is_closed=row["is_closed"], ownership=ownership,
        owner_display_name=row["owner_display_name"], next_action=action,
        claim_api_path=path + "/claim" if action == "claim" else None,
        review_api_path=path if action == "review" else None,
    )


async def get_reports(db, query, coordinator_id: int) -> HotspotReportsResponse:
    filters = resolve_filters(query)
    try:
        data = await query_safely(
            db, repository.list_reports, filters=filters, page=query.page, page_size=query.page_size,
        )
    except AnalysisUnavailable:
        return HotspotReportsResponse(
            state="unavailable", message=UNAVAILABLE, filters=filters,
            page=query.page, page_size=query.page_size,
        )
    return HotspotReportsResponse(
        state="ready" if data["total"] else "no_matches",
        message="Intake summaries only. Ownership is checked again when claiming or opening a case.",
        filters=filters, total=data["total"], page=query.page, page_size=query.page_size,
        items=[project_intake(row, coordinator_id) for row in data["items"]],
    )


async def get_intake(db, report_reference: str, coordinator_id: int) -> HotspotIntakeItem:
    row = await query_safely(db, repository.get_intake, report_reference=report_reference)
    if row is None:
        raise NotFoundError("Submitted report not found")
    return project_intake(row, coordinator_id)


async def get_case_context(db, report_reference: str, coordinator_id: int) -> HotspotContextResponse:
    try:
        row = await query_safely(
            db, repository.get_owned_context,
            report_reference=report_reference, coordinator_id=coordinator_id,
        )
    except AnalysisUnavailable:
        return HotspotContextResponse(state="unavailable", message=UNAVAILABLE, report_reference=report_reference)

    if row is None:
        raise NotFoundError("Owned report not found")
    site = site_projection(row)

    if site is None or row["observed_at"] is None:
        return HotspotContextResponse(
            state="insufficient_data", message="A named site and observation time are needed for area context.",
            report_reference=report_reference, site=site,
        )
    
    # The same 30-day window is passed back verbatim in the map link. An old
    # case opens its own observation period, not the current month's activity.
    observed = row["observed_at"].astimezone(MALAYSIA).date()
    query = HotspotQuery(
        site_id=site.site_id, observed_from=observed - timedelta(days=29), observed_to=observed,
    )
    analysis = await get_analysis(db, query)
    query_string = urlencode({
        "siteId": site.site_id, "observedFrom": analysis.filters.observed_from.isoformat(),
        "observedTo": analysis.filters.observed_to.isoformat(), "interval": analysis.filters.interval,
    })
    return HotspotContextResponse(
        state=analysis.state, message=analysis.message, report_reference=report_reference,
        site=site, filters=analysis.filters,
        report_count=analysis.summary.report_count if analysis.summary else None,
        last_successful_update_at=analysis.last_successful_update_at,
        analysis_api_path=f"{settings.api_v1_prefix}/coordinator/hotspots?{query_string}",
        analysis_query=query_string,
    )
