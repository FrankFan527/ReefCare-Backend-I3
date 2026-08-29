from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import (
    OAuth2PasswordRequestForm,
)

from app.api.dependencies.auth import (
    CurrentUserClaims,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.api.dependencies.rate_limit import (
    apply_login_rate_limit,
)
from app.core.exceptions import (
    AuthenticationError,
)
from app.repositories.auth_repository import (
    get_user_by_email,
)
from app.schemas.auth import (
    AuthResponse,
    UserResponse,
)
from app.services.auth_service import (
    authenticate_user,
    issue_session,
)


router = APIRouter()


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[
        Depends(apply_login_rate_limit),
    ],
)
async def login(
    db: DatabaseSession,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """
    Authenticate a ReefCare account.

    OAuth2 username is interpreted as the account email.
    """

    user = await get_user_by_email(
        db=db,
        email=form_data.username,
    )

    try:
        authenticated_user = authenticate_user(
            user=user,
            password=form_data.password,
        )

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc

    token, expires_in = issue_session(
        user_id=authenticated_user[
            "user_id"
        ],
        role_code=authenticated_user[
            "role_code"
        ],
    )

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse(
            id=authenticated_user[
                "user_id"
            ],
            display_name=authenticated_user[
                "display_name"
            ],
            role=authenticated_user[
                "role_code"
            ],
        ),
    )


@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_current_user(
    current_user: CurrentUserClaims,
):
    """
    Return the currently authenticated safe user projection.
    """

    return UserResponse(
        id=current_user["user_id"],
        display_name=current_user[
            "display_name"
        ],
        role=current_user["role"],
    )