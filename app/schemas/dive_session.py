# ---------------------------------------------------------------------------
# Dive Session schemas (US4.1).
#
# A Dive Session is the container that answers the mentor's question: divers
# visit several sites in a day, so which photos belong to which site? The
# observer picks the site once per dive and every report inherits it.
#
# Field names follow the API contract in the backend doc, not the raw column
# names. The repository aliases between them.
# ---------------------------------------------------------------------------
from datetime import date, datetime

from pydantic import BaseModel


class DiveSiteSummary(BaseModel):
    """
    The site a session took place at, as shown back to the observer.

    Carries no coordinates. public_area_label is included so the observer can
    tell "Renggis Island" from "Renggis Island, Tioman" when picking between
    sessions, without any precise position being involved.
    """

    dive_site_id: int
    name: str
    public_area_label: str


class DiveSessionResponse(BaseModel):
    """
    One of the signed-in observer's dive sessions.

    observer_id is deliberately absent: the endpoint only ever returns the
    caller's own sessions, so echoing the owner back adds nothing and would
    put an internal user id into a client payload.
    """

    dive_session_id: int

    # optional; the observer may not have named the dive
    label: str | None = None

    dive_date: date

    named_dive_site: DiveSiteSummary

    # optional approximate times, stored as time_in / time_out in the database
    approximate_start_time: datetime | None = None
    approximate_end_time: datetime | None = None