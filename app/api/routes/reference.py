from fastapi import APIRouter

from app.api.dependencies.db import DatabaseSession
from app.repositories.reference_repository import (
    list_active_threat_categories,
)
from app.schemas.report import (
    ThreatCategoryResponse,
)


router = APIRouter()


@router.get(
    "/threat-categories",
    response_model=list[
        ThreatCategoryResponse
    ],
)
async def get_threat_categories(
    db: DatabaseSession,
):
    rows = await list_active_threat_categories(
        db
    )

    return [
        ThreatCategoryResponse(
            **row
        )
        for row in rows
    ]