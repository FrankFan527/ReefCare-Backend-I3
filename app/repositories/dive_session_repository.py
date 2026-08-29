# ---------------------------------------------------------------------------
# Dive Session queries.
#
# Repositories own SQL and transactions; services own workflow and policy.
# Raw SQL through text(), matching the pattern in the rest of the backend.
# ---------------------------------------------------------------------------
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_my_dive_sessions(
    db: AsyncSession,
    observer_id: int,
) -> list:
    """
    Return the dive sessions belonging to one observer.

    The observer_id filter is the ownership boundary for this endpoint, and it
    is applied here in SQL rather than by filtering in Python afterwards. A row
    that was never selected cannot be leaked by a later mistake.

    Newest dive first, then newest created, so two sessions on the same day
    still come back in a stable order rather than whatever Postgres happens to
    return.
    """

    the_dive_session_result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.session_label   AS label,
                ds.dive_date,
                ds.time_in         AS approximate_start_time,
                ds.time_out        AS approximate_end_time,
                s.dive_site_id,
                s.name             AS dive_site_name,
                s.public_area_label
            FROM dive_session AS ds
            JOIN dive_site AS s
                ON s.dive_site_id = ds.dive_site_id
            WHERE ds.observer_id = :observer_id
            ORDER BY ds.dive_date DESC, ds.created_at DESC
            """
        ),
        {"observer_id": observer_id},
    )

    return the_dive_session_result.mappings().all()

async def count_sessions_on_date(
    db: AsyncSession,
    observer_id: int,
    dive_date,
) -> int:
    """
    How many sessions this observer already has on this date.

    Used to generate "Dive 1", "Dive 2" and so on, matching the convention
    already present in the demo seed data.
    """

    the_count_result = await db.execute(
        text(
            """
            SELECT COUNT(*) AS session_count
            FROM dive_session
            WHERE observer_id = :observer_id
              AND dive_date = :dive_date
            """
        ),
        {"observer_id": observer_id, "dive_date": dive_date},
    )

    return the_count_result.scalar_one()


async def create_dive_session(
    db: AsyncSession,
    observer_id: int,
    dive_site_id: int,
    dive_date,
    session_label: str | None,
    time_in,
    time_out,
) -> dict:
    """
    Insert one dive session and return it joined to its site.

    observer_id comes from the verified token, never from the request body,
    so an observer cannot create a session owned by somebody else.

    RETURNING gives back the generated id in the same round trip, and the
    second query fetches the site name for the response. The caller commits.
    """

    the_insert_result = await db.execute(
        text(
            """
            INSERT INTO dive_session
                (observer_id, dive_site_id, dive_date,
                 session_label, time_in, time_out)
            VALUES
                (:observer_id, :dive_site_id, :dive_date,
                 :session_label, :time_in, :time_out)
            RETURNING dive_session_id
            """
        ),
        {
            "observer_id": observer_id,
            "dive_site_id": dive_site_id,
            "dive_date": dive_date,
            "session_label": session_label,
            "time_in": time_in,
            "time_out": time_out,
        },
    )

    the_new_session_id = the_insert_result.scalar_one()

    # read the row back joined to its site, so the response matches the
    # shape returned by the list endpoint
    the_created_result = await db.execute(
        text(
            """
            SELECT
                ds.dive_session_id,
                ds.session_label   AS label,
                ds.dive_date,
                ds.time_in         AS approximate_start_time,
                ds.time_out        AS approximate_end_time,
                s.dive_site_id,
                s.name             AS dive_site_name,
                s.public_area_label
            FROM dive_session AS ds
            JOIN dive_site AS s
                ON s.dive_site_id = ds.dive_site_id
            WHERE ds.dive_session_id = :dive_session_id
            """
        ),
        {"dive_session_id": the_new_session_id},
    )

    return the_created_result.mappings().one()


async def dive_site_exists(
    db: AsyncSession,
    dive_site_id: int,
) -> bool:
    """
    Whether a dive site id refers to a real site.

    The foreign key would reject a bad id anyway, but that surfaces as a
    database error. Checking first lets the route return a clear 404 naming
    the field the observer got wrong.
    """

    the_site_result = await db.execute(
        text(
            """
            SELECT 1
            FROM dive_site
            WHERE dive_site_id = :dive_site_id
            """
        ),
        {"dive_site_id": dive_site_id},
    )

    return the_site_result.first() is not None