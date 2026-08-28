from pydantic import BaseModel

from app.core.enums import UserRole
from app.schemas.common import APIModel


class UserResponse(APIModel):
    id: int
    display_name: str
    role: UserRole


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(BaseModel):
    """
    OAuth2 login response.

    access_token and token_type must remain top-level
    snake_case fields so Swagger's OAuth2 password flow
    can read them correctly.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse