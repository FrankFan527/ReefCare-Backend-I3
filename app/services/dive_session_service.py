# ---------------------------------------------------------------------------
# Dive Session workflow (US4.1).
#
# Services own workflow and policy; repositories own SQL. This module decides
# what a valid session looks like and what to call it, then hands the values
# to the repository to persist.
# ---------------------------------------------------------------------------
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories.dive_session_repository import (
    count_sessions_on_date,
    dive_site_exists,
)


async def validate_dive_session(
    db: AsyncSession,
    named_dive_site_id: int,
) -> None:
    """
    Confirm the chosen site is real before attempting the insert.

    Shape and range checks already happened in DiveSessionCreate. The only
    thing left that needs the database is whether the site id exists, and
    that cannot be checked without a query.
    """

    the_site_is_real = await dive_site_exists(
        db=db,
        dive_site_id=named_dive_site_id,
    )

    if not the_site_is_real:
        raise NotFoundError(
            f"Dive site {named_dive_site_id} does not exist"
        )


async def generate_session_label(
    db: AsyncSession,
    observer_id: int,
    dive_date: date,
) -> str:
    """
    Build a display label for a session the observer did not name.

    Counts the observer's existing sessions on that date and numbers the new
    one after them, producing "Dive 1", "Dive 2" and so on. That matches the
    convention already used in the demo seed data, so generated and
    hand-written labels look the same in a list.

    This is a display convenience, not an identifier. Two observers diving on
    the same day will both have a "Dive 1", which is fine because sessions
    are only ever listed within one observer's own account.
    """

    the_existing_session_count = await count_sessions_on_date(
        db=db,
        observer_id=observer_id,
        dive_date=dive_date,
    )

    return f"Dive {the_existing_session_count + 1}"