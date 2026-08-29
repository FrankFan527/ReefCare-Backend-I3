from typing import Annotated

import jwt
from fastapi import (
    Depends,
    HTTPException,
    status,
)
from fastapi.security import (
    OAuth2PasswordBearer,
)

from app.api.dependencies.db import (
    DatabaseSession,
)
from app.core.security import (
    decode_access_token,
)
from app.repositories.auth_repository import (
    get_user_by_id,
)


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


async def validate_session(
    token: str,
    db: DatabaseSession,
) -> dict:
    """
    Validate both the signed JWT and the current database
    account state.

    The database remains authoritative for whether the user
    is active and which role the user currently holds.
    """

    try:
        payload = decode_access_token(
            token
        )

        subject = payload.get("sub")
        token_role = payload.get("role")

        if (
            subject is None
            or token_role is None
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Invalid authentication "
                    "credentials"
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            )

        try:
            user_id = int(subject)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Invalid authentication "
                    "credentials"
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            ) from exc

        user = await get_user_by_id(
            db=db,
            user_id=user_id,
        )

        if (
            user is None
            or not user["is_active"]
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Authentication is no longer valid"
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            )

        current_role = user[
            "role_code"
        ]

        if current_role != token_role:
            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                ),
                detail=(
                    "Authentication is no longer valid"
                ),
                headers={
                    "WWW-Authenticate": "Bearer",
                },
            )

        return {
            "user_id": user["user_id"],
            "role": current_role,
            "display_name": user[
                "display_name"
            ],
        }

    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail=(
                "Authentication token has expired"
            ),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc

    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail=(
                "Invalid authentication credentials"
            ),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc


async def require_authentication(
    token: Annotated[
        str,
        Depends(oauth2_scheme),
    ],
    db: DatabaseSession,
) -> dict:
    return await validate_session(
        token=token,
        db=db,
    )


CurrentUserClaims = Annotated[
    dict,
    Depends(require_authentication),
]