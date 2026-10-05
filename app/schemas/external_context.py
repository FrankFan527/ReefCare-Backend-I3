# ---------------------------------------------------------------------------
# US8.3 Selected external conservation or environmental context — contracts.
#
# Backend doc 6.9 fields: contextType, value/displayValue, unit, sourceName,
# sourceUrl, representedPeriod, retrievedAt, lastReviewedAt.
#
# Two dates travel with every value and must not be confused:
#
#   representedPeriod   the day the satellite measurement describes
#   retrievedAt         when ReefCare fetched it
#
# NOAA publishes about two days behind, so these always differ. Showing only
# the retrieval time would present a two-day-old measurement as today's.
# ---------------------------------------------------------------------------

from datetime import date, datetime
from enum import Enum

from pydantic import Field

from app.schemas.common import APIModel


class ExternalContextState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"

    # US9.3 uses the same rule: a site without a planning position is never
    # given a neighbouring site's value
    SITE_POSITION_UNAVAILABLE = "site_position_unavailable"


class ExternalContextItem(APIModel):
    context_type: str
    label: str

    value: float | None = None
    display_value: str
    unit: str | None = None

    represented_period_start: date
    represented_period_end: date

    retrieved_at: datetime
    last_reviewed_at: date | None = None

    # the 5 km grid cell the value describes. Two nearby sites can share one
    # cell, and showing it lets the UI say so honestly.
    provider_grid_latitude: float | None = None
    provider_grid_longitude: float | None = None


class ExternalContextResponse(APIModel):
    dive_site_id: int
    site_name: str
    public_area_label: str

    state: ExternalContextState
    message: str

    # US8.3 AC1: every value is identified by its source
    source_name: str | None = None
    source_url: str | None = None
    attribution: str | None = None

    items: list[ExternalContextItem] = Field(default_factory=list)

    # true when the provider could not be reached on this request and the
    # values shown are the last ones stored. Their dates stay accurate.
    showing_last_stored_values: bool = False

    # US8.3 AC2 / AC3: supplementary context, never a verdict on a report or
    # a statement that a site is safe
    interpretation_note: str = (
        "This is satellite-derived heat-stress context for the ocean area "
        "around the site, published by NOAA Coral Reef Watch. It describes "
        "regional sea conditions, not the reef at this exact spot, and it is "
        "not a forecast. It does not confirm or rule out anything reported "
        "to ReefCare."
    )
