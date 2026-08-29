# ---------------------------------------------------------------------------
# Dive Session workflow (US4.1).
#
# Services own workflow and transaction boundaries; repositories own SQL.
# The route below this layer only maps domain exceptions onto status codes,
# matching the pattern in case_service and case_ownership_service.
# ---------------------------------------------------------------------------
from datetime import date

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseOperationError, NotFoundError
from app.repositories.dive_session_repository import (
    count_sessions_on_date,
    create_dive_session,
    dive_site_exists,
    list_my_dive_sessions,
)


async def get_my_dive_sessions(
    db: AsyncSession,
    observer_id: int,
) -> list:
    """
    Return the dive sessions belonging to one observer.

    Read-only, so no transaction handling is needed. The observer filter is
    applied in SQL inside the repository rather than here, so a row that is
    not the caller's is never loaded in the first place.
    """

    return await list_my_dive_sessions(
        db=db,
        observer_id=observer_id,
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


async def create_my_dive_session(
    db: AsyncSession,
    observer_id: int,
    named_dive_site_id: int,
    dive_date: date,
    label: str | None = None,
    approximate_start_time=None,
    approximate_end_time=None,
) -> dict:
    """
    Create one dive session owned by this observer.

    Owns the whole unit of work: validation, labelling, insert and commit.
    The observer id is passed in from the verified token, never taken from
    the request body, so a session cannot be created for somebody else.

    A blank label is treated the same as no label. A client sending an empty
    string means "I did not name this dive", not "name it nothing".
    """

    await validate_dive_session(
        db=db,
        named_dive_site_id=named_dive_site_id,
    )

    the_session_label = label

    if the_session_label is None or the_session_label.strip() == "":
        the_session_label = await generate_session_label(
            db=db,
            observer_id=observer_id,
            dive_date=dive_date,
        )

    try:
        the_created_row = await create_dive_session(
            db=db,
            observer_id=observer_id,
            dive_site_id=named_dive_site_id,
            dive_date=dive_date,
            session_label=the_session_label,
            time_in=approximate_start_time,
            time_out=approximate_end_time,
        )

        await db.commit()

    except SQLAlchemyError as the_error:
        await db.rollback()
        raise DatabaseOperationError(
            "The dive session could not be created"
        ) from the_error

    return dict(the_created_row)