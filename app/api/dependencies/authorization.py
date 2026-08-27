from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.dependencies.auth import (
    CurrentUserClaims,
)
from app.core.enums import UserRole


def require_role(
    current_user: CurrentUserClaims,
    allowed_roles: set[UserRole],
):
    """
    Require the authenticated user's role code to match
    one of the allowed application roles.
    """

    current_role = current_user.get("role")

    allowed_role_codes = {
        role.value
        for role in allowed_roles
    }

    if current_role not in allowed_role_codes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You do not have permission "
                "to perform this action"
            ),
        )

    return current_user


def require_observer(
    current_user: CurrentUserClaims,
):
    return require_role(
        current_user,
        {
            UserRole.OBSERVER,
        },
    )


def require_coordinator(
    current_user: CurrentUserClaims,
):
    return require_role(
        current_user,
        {
            UserRole.CASE_COORDINATOR,
        },
    )


def require_system_admin(
    current_user: CurrentUserClaims,
):
    return require_role(
        current_user,
        {
            UserRole.SYSTEM_ADMIN,
        },
    )


CurrentObserver = Annotated[
    dict,
    Depends(require_observer),
]


CurrentCoordinator = Annotated[
    dict,
    Depends(require_coordinator),
]


CurrentSystemAdmin = Annotated[
    dict,
    Depends(require_system_admin),
]