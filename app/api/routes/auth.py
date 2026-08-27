from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends
from sqlalchemy import text

from app.api.dependencies.auth import CurrentUserClaims
from app.api.dependencies.db import DatabaseSession
from app.core.exceptions import AuthenticationError
from app.schemas.auth import (
    AuthResponse,
    TokenResponse,
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

    Swagger/OAuth2 uses the `username` field.
    For ReefCare, username is interpreted as email.
    """

    result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.email,
                u.display_name,
                u.password_hash,
                u.is_active,
                r.code AS role_code
            FROM app_user u
            JOIN app_role r
                ON r.role_id = u.role_id
            WHERE u.email = :email
            LIMIT 1
            """
        ),
        {
            "email": form_data.username,
        },
    )

    user = result.mappings().first()

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
                "WWW-Authenticate": "Bearer"
            },
        ) from exc

    token, expires_in = issue_session(
        user_id=authenticated_user["user_id"],
        role_code=authenticated_user["role_code"],
    )

    return AuthResponse(
        user=UserResponse(
            id=authenticated_user["user_id"],
            display_name=authenticated_user[
                "display_name"
            ],
            role=authenticated_user[
                "role_code"
            ],
        ),
        session=TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_in,
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
    result = await db.execute(
        text(
            """
            SELECT
                u.user_id,
                u.display_name,
                r.code AS role_code
            FROM app_user u
            JOIN app_role r
                ON r.role_id = u.role_id
            WHERE u.user_id = :user_id
              AND u.is_active = TRUE
            LIMIT 1
            """
        ),
        {
            "user_id": current_user["user_id"],
        },
    )

    user = result.mappings().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists",
        )

    return UserResponse(
        id=user["user_id"],
        display_name=user["display_name"],
        role=user["role_code"],
    )