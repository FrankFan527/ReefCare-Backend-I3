from app.core.enums import UserRole
from app.schemas.common import APIModel


class UserResponse(APIModel):
    id: int
    display_name: str
    role: UserRole


class AuthResponse(APIModel):
    """
    OAuth2 login response.

    access_token and token_type intentionally remain
    top-level so Swagger's OAuth2 password flow can consume
    the response automatically.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int

    user: UserResponse