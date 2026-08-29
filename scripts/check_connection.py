# ---------------------------------------------------------------------------
# One-off connection check. Proves the .env credentials reach Neon and that
# the reference data seeded by 02_seed_reference.sql is readable by whichever
# role we connected as.
#
# Windows note: async psycopg does not work on the default Proactor event
# loop, so a selector loop is installed first.
# ---------------------------------------------------------------------------
import asyncio
import selectors
import sys

from sqlalchemy import text

from app.db.session import AsyncSessionLocal


async def run_connection_check() -> None:
    async with AsyncSessionLocal() as the_database_session:

        # confirm which role we authenticated as and which database we landed in
        the_identity_result = await the_database_session.execute(
            text("SELECT current_user, current_database()")
        )
        print("connected as:", the_identity_result.first())

        # confirm the seeded dive sites are visible to this role
        the_site_result = await the_database_session.execute(
            text(
                """
                SELECT dive_site_id, name, public_area_label
                FROM dive_site
                ORDER BY dive_site_id
                LIMIT 5
                """
            )
        )

        print("dive sites:")
        for the_single_site in the_site_result.mappings().all():
            print(" ", dict(the_single_site))


if __name__ == "__main__":
    # windows needs a selector event loop for async psycopg
    if sys.platform == "win32":
        the_selector_event_loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(the_selector_event_loop)
        try:
            the_selector_event_loop.run_until_complete(run_connection_check())
        finally:
            the_selector_event_loop.close()
    else:
        asyncio.run(run_connection_check())