# ---------------------------------------------------------------------------
# Response schemas for the read-only reference endpoints.
#
# US4.1: the observer picks a named site during the location step. This shape
# deliberately omits centre_latitude and centre_longitude, so a selection
# screen cannot accidentally render a precise-looking point.
# ---------------------------------------------------------------------------
from app.schemas.common import APIModel

class DiveSiteResponse(APIModel):
    """A named dive site as offered to an observer choosing a location."""

    dive_site_id: int
    name: str

    # the generalised label shown publicly, e.g. "Tioman Island"
    public_area_label: str

    region: str | None = None

    # The published centre of a named site, not a report location. Nullable
    # because a site added later may not have been sourced yet, and an absent
    # coordinate is a truthful answer rather than a gap to fill.
    centre_latitude: float | None = None
    centre_longitude: float | None = None

    # How large the site is. Returned with the coordinate so the interface can
    # show the area a dive-site-only report covers rather than a false point.
    default_uncertainty_metres: int | None = None