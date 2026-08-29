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

async def create_observer_user(
    db: AsyncSession,
    email: str,
    display_name: str,
    password_hash: str,
):
    """
    Insert one self-registered account.

    SECURITY: the role is resolved inside the statement by looking up
    app_role.code = 'observer'. It is not a parameter, so no caller can create
    a coordinator or administrator through this path even by mistake.

    The email UNIQUE constraint is the authoritative duplicate check. email is
    citext, so the comparison is case-insensitive and Aisha@example.com
    collides with aisha@example.com without any lowercasing here.

    The caller commits.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO app_user
                (role_id, email, display_name, password_hash, is_active)
            SELECT
                r.role_id,
                :email,
                :display_name,
                :password_hash,
                TRUE
            FROM app_role r
            WHERE r.code = 'observer'
            RETURNING
                user_id,
                email,
                display_name
            """
        ),
        {
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
        },
    )

    return result.mappings().first()