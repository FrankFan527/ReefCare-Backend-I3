from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_access_token


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


def validate_session(
    token: str,
) -> dict:
    """
    Decode and validate the JWT.

    Expected claims:
    - sub: app_user.user_id
    - role: app_role.code
    """

    try:
        payload = decode_access_token(token)

        user_id = payload.get("sub")
        role = payload.get("role")

        if user_id is None or role is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        try:
            parsed_user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )

        return {
            "user_id": parsed_user_id,
            "role": role,
        }

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
        )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )


def require_authentication(
    token: Annotated[
        str,
        Depends(oauth2_scheme),
    ],
) -> dict:
    return validate_session(token)


CurrentUserClaims = Annotated[
    dict,
    Depends(require_authentication),
]