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