from pydantic import EmailStr, Field, field_validator

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

class RegistrationCreate(APIModel):
    """
    Self-registration request (US1.1).

    SECURITY: there is deliberately no role field. Self-registration always
    creates an observer. Coordinator and administrator accounts are created by
    an administrator, because a coordinator can read every report in the
    system including precise coordinates, which is exactly what the location
    privacy design exists to protect.
    """

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, the_value: str) -> str:
        """A name made only of spaces is not a name."""

        the_trimmed_name = the_value.strip()

        if the_trimmed_name == "":
            raise ValueError("display_name must not be empty")

        return the_trimmed_name

    @field_validator("password")
    @classmethod
    def password_must_be_reasonable(cls, the_value: str) -> str:
        """
        Reject passwords that are long but trivially weak.

        Length is the strongest single signal, which is why the minimum is 12
        rather than 8. This adds only a check that the password is not one
        repeated character, which passes a length rule while carrying almost
        no entropy.
        """

        if len(set(the_value)) < 4:
            raise ValueError(
                "password must contain at least 4 different characters"
            )

        return the_value


class RegistrationResponse(APIModel):
    """
    Confirmation that an account was created.

    No token is returned. The client calls POST /auth/login next, which keeps
    registration single-purpose rather than duplicating the token logic.
    """

    id: int
    email: EmailStr
    display_name: str
    role: UserRole