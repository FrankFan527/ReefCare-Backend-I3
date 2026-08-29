from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    verify_password,
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