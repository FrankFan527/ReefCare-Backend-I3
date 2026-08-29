from sqlalchemy.exc import (
    IntegrityError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    DatabaseOperationError,
)
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.repositories.auth_repository import (
    create_observer_user,
    get_user_by_email,
)


def authenticate_user(
    user,
    password: str,
):
    """
    Validate credentials for a repository-returned user.
    """

    if user is None:
        raise AuthenticationError(
            "Invalid credentials"
        )

    if not user["password_hash"]:
        raise AuthenticationError(
            "Invalid credentials"
        )

    if not user["is_active"]:
        raise AuthenticationError(
            "Invalid credentials"
        )

    if not verify_password(
        password,
        user["password_hash"],
    ):
        raise AuthenticationError(
            "Invalid credentials"
        )

    return user


async def register_observer(
    db: AsyncSession,
    email: str,
    display_name: str,
    password: str,
) -> dict:
    """
    Create a self-registered observer account.
    """

    the_existing_user = await get_user_by_email(
        db=db,
        email=email,
    )

    if the_existing_user is not None:
        raise ConflictError(
            "An account with that email already exists"
        )

    the_password_hash = hash_password(
        password
    )

    try:
        the_created_user = (
            await create_observer_user(
                db=db,
                email=email,
                display_name=display_name,
                password_hash=the_password_hash,
            )
        )

        if the_created_user is None:
            await db.rollback()

            raise DatabaseOperationError(
                "The observer role is not configured"
            )

        await db.commit()

    except IntegrityError as the_error:
        await db.rollback()

        raise ConflictError(
            "An account with that email already exists"
        ) from the_error

    except SQLAlchemyError as the_error:
        await db.rollback()

        raise DatabaseOperationError(
            "The account could not be created"
        ) from the_error

    return {
        "id": the_created_user["user_id"],
        "email": the_created_user["email"],
        "display_name": (
            the_created_user["display_name"]
        ),
        "role": "observer",
    }


def issue_session(
    user_id: int,
    role_code: str,
) -> tuple[str, int]:
    """
    Issue a short-lived JWT.
    """

    return create_access_token(
        user_id=user_id,
        role=role_code,
    )