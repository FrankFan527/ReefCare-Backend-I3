from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_users(
    db: AsyncSession,
    page: int,
    page_size: int,
):
    """
    Return a paginated safe account list.

    Password hashes and external_auth_id are never selected.
    """

    offset = (
        page - 1
    ) * page_size

    rows_result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.email,
                u.display_name,
                u.is_active,
                u.created_at,
                r.code AS role_code

            FROM app_user AS u

            JOIN app_role AS r
                ON r.role_id =
                   u.role_id

            ORDER BY
                u.created_at DESC,
                u.user_id DESC

            LIMIT :page_size
            OFFSET :offset
            """
        ),
        {
            "page_size": page_size,
            "offset": offset,
        },
    )

    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM app_user
            """
        )
    )

    return (
        rows_result.mappings().all(),
        count_result.scalar_one(),
    )


async def get_admin_user_by_id(
    db: AsyncSession,
    user_id: int,
):
    """
    Return one safe account projection.
    """

    result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.email,
                u.display_name,
                u.is_active,
                u.created_at,
                r.code AS role_code

            FROM app_user AS u

            JOIN app_role AS r
                ON r.role_id =
                   u.role_id

            WHERE
                u.user_id = :user_id

            LIMIT 1
            """
        ),
        {
            "user_id": user_id,
        },
    )

    return (
        result
        .mappings()
        .first()
    )


async def get_admin_user_by_email(
    db: AsyncSession,
    email: str,
):
    """
    Resolve an account by email for duplicate checks.
    """

    result = await db.execute(
        text(
            """
            SELECT
                user_id,
                email
            FROM app_user
            WHERE email = :email
            LIMIT 1
            """
        ),
        {
            "email": email,
        },
    )

    return (
        result
        .mappings()
        .first()
    )


async def create_managed_user(
    db: AsyncSession,
    email: str,
    display_name: str,
    password_hash: str,
    role_code: str,
):
    """
    Create a managed account.

    The role is resolved using app_role.code so Python never
    depends on numeric role IDs.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO app_user
                (
                    role_id,
                    email,
                    display_name,
                    password_hash,
                    is_active
                )

            SELECT
                r.role_id,
                :email,
                :display_name,
                :password_hash,
                TRUE

            FROM app_role AS r

            WHERE
                r.code = :role_code

            RETURNING
                user_id,
                email,
                display_name,
                is_active,
                created_at
            """
        ),
        {
            "email": email,
            "display_name": display_name,
            "password_hash": password_hash,
            "role_code": role_code,
        },
    )

    return (
        result
        .mappings()
        .first()
    )


async def update_managed_user(
    db: AsyncSession,
    user_id: int,
    acting_admin_id: int,
    display_name: str | None,
    is_active: bool | None,
):
    """
    Update administrator-editable account fields.

    Role changes are intentionally excluded.

    Routed through reefcare_update_user_profile() rather than a direct UPDATE.
    reefcare_app holds SELECT and INSERT on app_user and deliberately no
    UPDATE, because that table carries the password hash. A direct UPDATE is
    refused by PostgreSQL and surfaces as a 500.

    This was not caught locally because development connects as the database
    owner, which bypasses every grant in the schema.
    """

    result = await db.execute(
        text(
            """
            SELECT
                user_id,
                email,
                display_name,
                role_code,
                is_active

            FROM reefcare_update_user_profile(
                :user_id,
                :acting_admin_id,
                :display_name,
                :is_active
            )
            """
        ),
        {
            "user_id": user_id,
            "acting_admin_id": acting_admin_id,
            "display_name": display_name,
            "is_active": is_active,
        },
    )

    return (
        result
        .mappings()
        .first()
    )

async def approve_coordinator_role(
    db: AsyncSession,
    user_id: int,
    acting_admin_id: int,
):
    """
    Persist coordinator access by changing the user's canonical PostgreSQL
    role.

    The dedicated endpoint is the only normal admin API path for coordinator
    promotion.

    Routed through reefcare_approve_coordinator() for the same reason as
    update_managed_user above: the application role cannot UPDATE app_user.

    The function enforces more than the previous UPDATE did. It promotes only
    from observer, so calling it on an administrator cannot silently demote
    them, and it refuses a deactivated target, which would otherwise create a
    coordinator who cannot log in.
    """

    result = await db.execute(
        text(
            """
            SELECT
                user_id,
                email,
                display_name,
                role_code,
                is_active

            FROM reefcare_approve_coordinator(
                :user_id,
                :acting_admin_id
            )
            """
        ),
        {
            "user_id": user_id,
            "acting_admin_id": acting_admin_id,
        },
    )

    return (
        result
        .mappings()
        .first()
    )