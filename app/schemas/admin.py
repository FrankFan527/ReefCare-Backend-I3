from datetime import datetime

from pydantic import (
    EmailStr,
    Field,
    field_validator,
)

from app.core.enums import UserRole
from app.schemas.common import APIModel


class AdminUserResponse(APIModel):
    """
    Safe administrator-facing account projection.

    Password hashes and external authentication identifiers
    are deliberately excluded.
    """

    id: int
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class AdminUserListResponse(APIModel):
    items: list[AdminUserResponse]
    page: int
    page_size: int
    total: int


class AdminUserCreate(APIModel):
    """
    Create a managed ReefCare account.

    Coordinators are not created directly through this model.
    A coordinator must be approved through the dedicated
    approve-coordinator endpoint.

    System administrators cannot be created through this
    endpoint.
    """

    email: EmailStr

    display_name: str = Field(
        min_length=1,
        max_length=100,
    )

    password: str = Field(
        min_length=12,
        max_length=128,
    )

    role: UserRole = UserRole.OBSERVER

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(
        cls,
        value: str,
    ) -> str:
        value = value.strip()

        if value == "":
            raise ValueError(
                "display_name must not be empty"
            )

        return value

    @field_validator("password")
    @classmethod
    def password_must_be_reasonable(
        cls,
        value: str,
    ) -> str:
        if len(set(value)) < 4:
            raise ValueError(
                "password must contain at least "
                "4 different characters"
            )

        return value

    @field_validator("role")
    @classmethod
    def role_must_be_admin_creatable(
        cls,
        value: UserRole,
    ) -> UserRole:
        permitted_roles = {
            UserRole.OBSERVER,
            UserRole.CONSERVATION_RESPONDER,
            UserRole.DIVE_OPERATOR,
        }

        if value not in permitted_roles:
            raise ValueError(
                "role must be one of: "
                "observer, conservation_responder, "
                "dive_operator"
            )

        return value


class AdminUserUpdate(APIModel):
    """
    Editable account fields.

    Role is intentionally absent.

    Coordinator promotion is handled only through the
    dedicated approve-coordinator endpoint.
    """

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if value == "":
            raise ValueError(
                "display_name must not be empty"
            )

        return value


class CoordinatorApprovalResponse(APIModel):
    """
    Confirmation that coordinator access was approved.
    """

    id: int
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool