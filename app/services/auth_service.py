from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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

    The same error is used for unknown users and incorrect
    passwords to avoid account enumeration.
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
    Create a self-registered observer account (US1.1).

    Owns the whole unit of work: duplicate check, hashing, insert and commit.

    The duplicate check is a courtesy, not the guarantee. Two simultaneous
    registrations could both pass it, and the app_user email UNIQUE constraint
    is what actually prevents the second insert. IntegrityError is caught and
    reported the same way, so the outcome is identical either way.

    The password is hashed here and never logged, stored or returned.
    """

    the_existing_user = await get_user_by_email(db=db, email=email)

    if the_existing_user is not None:
        raise ConflictError("An account with that email already exists")

    the_password_hash = hash_password(password)

    try:
        the_created_user = await create_observer_user(
            db=db,
            email=email,
            display_name=display_name,
            password_hash=the_password_hash,
        )

        if the_created_user is None:
            # the observer role is missing from app_role, which means the
            # reference data was not seeded
            await db.rollback()
            raise DatabaseOperationError(
                "The observer role is not configured"
            )

        await db.commit()

    except IntegrityError as the_error:
        # the UNIQUE constraint caught a duplicate this request did not see
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
        "display_name": the_created_user["display_name"],
        "role": "observer",
    }

def issue_session(
    user_id: int,
    role_code: str,
) -> tuple[str, int]:
    """
    Issue a short-lived JWT containing the stable database
    user id and app_role.code.
    """

    return create_access_token(
        user_id=user_id,
        role=role_code,
    )


async def register_observer(
    db: AsyncSession,
    email: str,
    display_name: str,
    password: str,
) -> dict:
    """
    Create a self-registered observer account (US1.1).

    Owns the whole unit of work: duplicate check, hashing, insert and commit.

    The duplicate check is a courtesy, not the guarantee. Two simultaneous
    registrations could both pass it, and the app_user email UNIQUE constraint
    is what actually prevents the second insert. IntegrityError is caught and
    reported the same way, so the outcome is identical either way.

    The password is hashed here and never logged, stored or returned.
    """

    the_existing_user = await get_user_by_email(db=db, email=email)

    if the_existing_user is not None:
        raise ConflictError("An account with that email already exists")

    the_password_hash = hash_password(password)

    try:
        the_created_user = await create_observer_user(
            db=db,
            email=email,
            display_name=display_name,
            password_hash=the_password_hash,
        )

        if the_created_user is None:
            # the observer role is missing from app_role, which means the
            # reference data was not seeded
            await db.rollback()
            raise DatabaseOperationError(
                "The observer role is not configured"
            )

        await db.commit()

    except IntegrityError as the_error:
        # the UNIQUE constraint caught a duplicate this request did not see
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
        "display_name": the_created_user["display_name"],
        "role": "observer",
    }