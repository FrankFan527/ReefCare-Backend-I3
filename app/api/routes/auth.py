from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import (
    CurrentUserClaims,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.core.exceptions import (
    AuthenticationError,
)
from app.repositories.auth_repository import (
    get_user_by_email,
    get_user_by_id,
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
)
async def login(
    db: DatabaseSession,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """
    Authenticate a ReefCare user.

    OAuth2 uses the `username` field.
    For ReefCare, username is interpreted as the user's email.

    The access token is returned at the top level so that
    Swagger UI can correctly use the OAuth2 password flow.
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
        user_id=authenticated_user["user_id"],
        role_code=authenticated_user[
            "role_code"
        ],
    )

    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse(
            id=authenticated_user["user_id"],
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
    db: DatabaseSession,
):
    """
    Return the currently authenticated ReefCare user.
    """

    user = await get_user_by_id(
        db=db,
        user_id=current_user["user_id"],
    )

    if (
        user is None
        or not user["is_active"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authenticated user is no "
                "longer available"
            ),
        )

    return UserResponse(
        id=user["user_id"],
        display_name=user["display_name"],
        role=user["role_code"],
    )