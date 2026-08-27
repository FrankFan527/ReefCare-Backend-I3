from fastapi import HTTPException, status

from app.api.dependencies.auth import CurrentUserClaims
from app.core.enums import UserRole


def require_role(
    current_user: CurrentUserClaims,
    allowed_roles: set[UserRole],
):
    current_role = current_user["role"]

    if current_role not in {
        role.value for role in allowed_roles
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )

    return current_user