# ---------------------------------------------------------------------------
# Response schemas for the read-only reference endpoints.
#
# US4.1: the observer picks a named site during the location step. This shape
# deliberately omits centre_latitude and centre_longitude, so a selection
# screen cannot accidentally render a precise-looking point.
# ---------------------------------------------------------------------------
from pydantic import BaseModel


class DiveSiteResponse(BaseModel):
    """A named dive site as offered to an observer choosing a location."""

    dive_site_id: int
    name: str

    # the generalised label shown publicly, e.g. "Tioman Island"
    public_area_label: str

    region: str | None = None