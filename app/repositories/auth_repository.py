from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_user_by_email(
    db: AsyncSession,
    email: str,
):
    """
    Retrieve authentication fields for one user.

    app_role.code is returned as the stable application
    role identifier.
    """

    result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.email,
                u.display_name,
                u.password_hash,
                u.is_active,
                r.code AS role_code

            FROM app_user u

            JOIN app_role r
                ON r.role_id = u.role_id

            WHERE u.email = :email

            LIMIT 1
            """
        ),
        {
            "email": email,
        },
    )

    return result.mappings().first()


async def get_user_by_id(
    db: AsyncSession,
    user_id: int,
):
    """
    Retrieve the safe authenticated-user projection.
    """

    result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.display_name,
                u.is_active,
                r.code AS role_code

            FROM app_user u

            JOIN app_role r
                ON r.role_id = u.role_id

            WHERE u.user_id = :user_id

            LIMIT 1
            """
        ),
        {
            "user_id": user_id,
        },
    )

    return result.mappings().first()