from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_report_location(
    db: AsyncSession,
    report_reference: str,
    user_id: int,
):
    """
    Retrieve precise location only through
    reefcare_report_location().

    The database decides whether the user is authorised.

    Authorised:
    - submitting observer
    - claiming coordinator

    Unauthorised:
    - zero rows
    """

    result = await db.execute(
        text(
            """
            SELECT *
            FROM reefcare_report_location(
                :report_reference,
                :user_id
            )
            """
        ),
        {
            "report_reference": report_reference,
            "user_id": user_id,
        },
    )

    return result.mappings().first()