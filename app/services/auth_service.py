from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, verify_password


def authenticate_user(
    user,
    password: str,
):
    if user is None:
        raise AuthenticationError("Invalid credentials")

    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid credentials")

    if not user.is_active:
        raise AuthenticationError("Invalid credentials")

    return user


def issue_session(user) -> tuple[str, int]:
    token, expires_in = create_access_token(
        user_id=user.id,
        role=user.role.value,
    )

    return token, expires_in