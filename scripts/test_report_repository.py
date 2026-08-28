import asyncio
from datetime import datetime, timezone

from app.db.session import AsyncSessionLocal
from app.repositories.report_repository import (
    get_submission_confirmation,
    submit_report,
)

async def main():
    async with AsyncSessionLocal() as db:

        result = await db.execute(
            __import__(
                "sqlalchemy"
            ).text(
                """
                SELECT
                    u.user_id,
                    ds.dive_session_id
                FROM app_user u
                JOIN dive_session ds
                    ON ds.observer_id =
                       u.user_id
                WHERE u.email =
                    'aisha.demo@example.com'
                  AND ds.session_label =
                    'Dive 1'
                LIMIT 1
                """
            )
        )

        row = result.mappings().one()

        try:
            reference = await submit_report(
                db=db,

                observer_id=row["user_id"],

                dive_session_id=(
                    row["dive_session_id"]
                ),

                threat_category_code=(
                    "ghost_gear"
                ),

                description=(
                    "Repository integration test"
                ),

                observed_at=(
                    datetime.now(
                        timezone.utc
                    )
                ),

                location_source_code=(
                    "named_dive_site"
                ),

                location_confidence_code=(
                    "dive_site_only"
                ),

                evidence=[
                    {
                        "media_type": "photo",
                        "file_reference":
                            "test/repository/photo.jpg",
                        "captured_at": None,
                    }
                ],

                estimated_depth_metres=10.0,
                latitude=None,
                longitude=None,

                relocation_notes=(
                    "Repository test"
                ),
            )

            print(
                "Generated reference:",
                reference,
            )

            confirmation = await get_submission_confirmation(
                db=db,
                report_reference=reference,
                observer_id=row["user_id"],
            )

            print(
                "Confirmation:",
                dict(confirmation)
                if confirmation
                else None,
            )

            # Testing only — don't keep it.
            await db.rollback()

        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())