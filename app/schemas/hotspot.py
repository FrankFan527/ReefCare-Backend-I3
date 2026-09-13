"""US5.6 contracts. Only generalised geography and intake-safe data belong here."""

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.schemas.common import APIModel


class HotspotThreat(str, Enum):
    GHOST_GEAR = "ghost_gear"
    CORAL_BLEACHING = "coral_bleaching"
    MARINE_DEBRIS = "marine_debris"
    PHYSICAL_DAMAGE = "physical_damage"
    UNSURE = "unsure"


class HotspotQuery(APIModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int | None = Field(default=None, gt=0)
    area: str | None = Field(default=None, min_length=1, max_length=200)
    region: str | None = Field(default=None, min_length=1, max_length=200)
    threat: HotspotThreat | None = None
    observed_from: date | None = None
    observed_to: date | None = None
    interval: Literal["day", "week", "month"] = "week"

    @model_validator(mode="after")
    def validate_period(self):
        if (self.observed_from is None) != (self.observed_to is None):
            raise ValueError("Supply both observedFrom and observedTo, or neither")
        if self.observed_from is not None:
            days = (self.observed_to - self.observed_from).days
            if days < 0 or days >= 366:
                raise ValueError("Observation period must be 1 to 366 inclusive calendar days")
            if self.observed_from.year < 2 or self.observed_to.year > 9998:
                raise ValueError("Observation dates must allow timezone and calendar interval calculation")
        for value in (self.area, self.region):
            if value is not None and not value.strip():
                raise ValueError("Area and region must not be blank")
        return self


class HotspotReportsQuery(HotspotQuery):
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: int = Field(default=20, ge=1, le=100)


class HotspotFilters(APIModel):
    site_id: int | None = None
    area: str | None = None
    region: str | None = None
    threat: HotspotThreat | None = None
    observed_from: date
    observed_to: date
    interval: Literal["day", "week", "month"]
    timezone: Literal["Asia/Kuala_Lumpur"] = "Asia/Kuala_Lumpur"


class HotspotSite(APIModel):
    site_id: int
    name: str
    area: str | None = None
    region: str | None = None


class ThreatOption(APIModel):
    code: str
    label: str


class ThreatCount(ThreatOption):
    report_count: int = Field(ge=0)


class FrequencyBucket(APIModel):
    # Calendar intervals; first/last buckets may only partly intersect the filter.
    bucket_start: date
    bucket_end_exclusive: date
    included_from: date
    included_to: date
    is_partial: bool
    report_count: int = Field(ge=0)


class HotspotSummary(APIModel):
    report_count: int
    threat_breakdown: list[ThreatCount]
    frequency: list[FrequencyBucket]
    trend_state: Literal["available", "insufficient_history"]
    trend_message: str


class GeneralisedMapLocation(APIModel):
    latitude: float
    longitude: float
    uncertainty_metres: int
    basis: str


class HotspotSiteSummary(HotspotSummary):
    site: HotspotSite
    map_location: GeneralisedMapLocation | None = None


class HotspotQuality(APIModel):
    matching_report_count: int
    included_report_count: int
    excluded_missing_site_count: int
    # Cannot be assigned to this period; scoped only by area/site/threat.
    undated_report_count: int
    mapped_report_count: int
    unmapped_report_count: int


class HotspotMetadata(APIModel):
    count_basis: str = "Individual submitted reports, not distinct or confirmed incidents."
    location_basis: str = "Named dive site linked through each report's dive session."
    selection_basis: str = (
        "Exact membership of configured site IDs and area/region labels; "
        "no radius, underwater positioning or point-in-polygon calculation."
    )
    time_basis: str = (
        "report.observed_at in Asia/Kuala_Lumpur; inclusive calendar dates. "
        "Submission time is never substituted for observation time."
    )
    interpretation: str = (
        "Reporting frequency does not establish ecological risk, severity, safety, "
        "absence of threats or field verification."
    )


class HotspotAnalysisResponse(APIModel):
    state: Literal["ready", "no_matches", "insufficient_data", "unavailable"]
    message: str
    filters: HotspotFilters
    last_successful_update_at: datetime | None = None
    metadata: HotspotMetadata = Field(default_factory=HotspotMetadata)
    summary: HotspotSummary | None = None
    sites: list[HotspotSiteSummary] = Field(default_factory=list)
    data_quality: HotspotQuality | None = None
    map_state: Literal["ready", "partial", "no_matches", "insufficient_data", "unavailable"]
    map_message: str


class HotspotOptionsResponse(APIModel):
    state: Literal["ready", "unavailable"]
    message: str
    sites: list[HotspotSite] = Field(default_factory=list)
    threats: list[ThreatOption] = Field(default_factory=list)
    intervals: list[str] = Field(default_factory=lambda: ["day", "week", "month"])
    default_filters: HotspotFilters
    max_period_days: int = 366


class HotspotIntakeItem(APIModel):
    report_reference: str
    site: HotspotSite | None = None
    threat: str
    threat_code: str
    observed_at: datetime | None = None
    submitted_at: datetime
    status_code: str
    status_label: str
    is_closed: bool
    ownership: Literal["unclaimed", "mine", "other"]
    owner_display_name: str | None = None
    next_action: Literal["claim", "review", "assigned_summary", "restricted_summary"]
    claim_api_path: str | None = None
    review_api_path: str | None = None


class HotspotReportsResponse(APIModel):
    state: Literal["ready", "no_matches", "unavailable"]
    message: str
    filters: HotspotFilters
    items: list[HotspotIntakeItem] = Field(default_factory=list)
    total: int | None = None
    page: int
    page_size: int


class HotspotContextResponse(APIModel):
    state: Literal["ready", "no_matches", "insufficient_data", "unavailable"]
    message: str
    report_reference: str
    site: HotspotSite | None = None
    filters: HotspotFilters | None = None
    report_count: int | None = None
    last_successful_update_at: datetime | None = None
    analysis_api_path: str | None = None
    analysis_query: str | None = None
    metadata: HotspotMetadata = Field(default_factory=HotspotMetadata)
