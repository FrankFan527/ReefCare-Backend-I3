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
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.schemas.common import APIModel
MALAYSIA_TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")

class DiveSiteSummary(APIModel):
    """
    The site a session took place at, as shown back to the observer.

    Carries no coordinates. public_area_label is included so the observer can
    tell one site from another when choosing between sessions, without any
    precise position being involved.
    """

    dive_site_id: int
    name: str
    public_area_label: str


class DiveSessionResponse(APIModel):
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


class DiveSessionCreate(APIModel):
    """
    What an observer supplies to create a dive session.

    named_dive_site_id and dive_date are required because the dive_session
    table requires both. Everything else stays optional: US4.1 AC2 keeps the
    form short so that logging a dive does not feel like paperwork.
    """

    named_dive_site_id: int = Field(gt=0)
    dive_date: date

    # optional; the service generates one when the observer leaves it blank
    label: str | None = Field(default=None, max_length=100)

    approximate_start_time: datetime | None = None
    approximate_end_time: datetime | None = None

    @model_validator(mode="after")
    def check_dive_date_is_not_in_the_future(self):
        """
        A dive cannot have happened after today in Malaysia.

        Compared against the local date rather than UTC. An earlier version
        allowed a day of tolerance to avoid rejecting early-morning dives,
        which had the side effect of accepting tomorrow's date entirely.
        Using the actual local date removes both problems.
        """

        the_today_in_malaysia = datetime.now(MALAYSIA_TIMEZONE).date()

        if self.dive_date > the_today_in_malaysia:
            raise ValueError("dive_date cannot be in the future")

        return self

    @model_validator(mode="after")
    def check_times_are_in_order(self):
        """
        Mirror the dive_session_time_order CHECK constraint.

        Postgres would reject this anyway, but catching it here returns a
        readable 422 naming the field instead of a raw database error.
        """

        if (
            self.approximate_start_time is not None
            and self.approximate_end_time is not None
            and self.approximate_end_time < self.approximate_start_time
        ):
            raise ValueError(
                "approximate_end_time cannot be before approximate_start_time"
            )

        return self