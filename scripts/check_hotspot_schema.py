"""Read-only US5.6 compatibility check against DATABASE_URL from your .env.

Run with the application's restricted DB role, after configuring .env. This
checks the columns/types used by US5.6, then executes a one-day aggregate query.
It never creates tables, changes reports or prints report data/credentials.
"""

import asyncio
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.db.session import AsyncSessionLocal, engine
from app.repositories import hotspot_repository as repository
from app.schemas.hotspot import HotspotFilters


REQUIRED = {
    "report": {"report_id", "report_reference", "observed_at", "submitted_at", "deleted_at",
               "current_status_id", "threat_category_id", "dive_session_id", "claimed_by_user_id"},
    "case_status": {"case_status_id", "code", "internal_label", "is_terminal"},
    "threat_category": {"threat_category_id", "code", "label"},
    "dive_site": {"dive_site_id", "name", "public_area_label", "region"},
    "dive_session": {"dive_session_id", "dive_site_id"},
    "app_user": {"user_id", "display_name"},
}


async def main():
    try:
        async with AsyncSessionLocal() as db:
            for table, columns in REQUIRED.items():
                # Identifiers come only from the fixed developer-owned allowlist.
                await db.execute(text(f"SELECT {', '.join(sorted(columns))} FROM {table} LIMIT 0"))
            result = await db.execute(text("""
                SELECT a.atttypid = 'timestamptz'::regtype
                FROM pg_attribute a
                WHERE a.attrelid = 'report'::regclass AND a.attname = 'observed_at'
            """))
            if result.scalar_one() is not True:
                raise ValueError("report.observed_at must use timestamp with time zone")
            today = datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date()
            await repository.get_analysis(db, HotspotFilters(observed_from=today, observed_to=today, interval="day"))
            await repository.list_sites(db)
            await repository.list_reports(db, HotspotFilters(observed_from=today, observed_to=today, interval="day"), 1, 1)
            await db.rollback()
            print("US5.6 schema, timestamp type and aggregate/intake read permissions passed.")
    except Exception as exc:
        # SQLAlchemy errors can embed a DSN or SQL parameters. Keep output safe.
        print(f"US5.6 compatibility check failed ({type(exc).__name__}). Verify canonical schema and application-role permissions.")
        return 1
    finally:
        await engine.dispose()
    return 0


raise SystemExit(asyncio.run(main()))
