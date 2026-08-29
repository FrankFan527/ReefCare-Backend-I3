from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from sqlalchemy import text

from app.api.dependencies.db import (
    DatabaseSession,
)


router = APIRouter()


@router.get(
    "/health",
)
async def health_check():
    """
    Process liveness check.

    This endpoint deliberately does not expose database,
    storage, environment, or secret information.
    """

    return {
        "status": "ok",
        "service": "ReefCare MY Backend",
    }


@router.get(
    "/ready",
)
async def readiness_check(
    db: DatabaseSession,
):
    """
    Verify that the backend can reach its critical database
    dependency before accepting normal traffic.
    """

    try:
        result = await db.execute(
            text(
                """
                SELECT 1
                """
            )
        )

        result.scalar_one()

    except Exception as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail="Service is not ready",
        ) from exc

    return {
        "status": "ready",
    }