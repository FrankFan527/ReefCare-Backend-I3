from fastapi import (
    APIRouter,
    HTTPException,
    Response,
    status,
)

from app.api.dependencies.authorization import (
    CurrentCoordinator,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.services.evidence_service import (
    EvidenceStorageError,
    get_case_evidence_file,
)


router = APIRouter()


@router.get(
    "/reports/{report_reference}/evidence/{evidence_id}",
    response_class=Response,
    responses={
        200: {
            "description": "Private evidence image",
            "content": {
                "image/jpeg": {},
                "image/png": {},
                "image/webp": {},
            },
        },
        401: {
            "description": "Unauthenticated",
        },
        403: {
            "description":
                "Caller is not the current case owner",
        },
        404: {
            "description":
                "Report/evidence not found",
        },
        500: {
            "description":
                "Private evidence could not be loaded",
        },
    },
)
async def get_case_evidence(
    report_reference: str,
    evidence_id: int,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Stream one private evidence image for an owned case.

    The frontend receives the image bytes only.
    The private Supabase file_reference/object key
    is never returned.
    """

    try:
        evidence_file = (
            await get_case_evidence_file(
                db=db,
                report_reference=(
                    report_reference
                ),
                evidence_id=evidence_id,
                coordinator_id=(
                    current_coordinator[
                        "user_id"
                    ]
                ),
            )
        )

    except EvidenceStorageError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load evidence",
        ) from exc

    return Response(
        content=evidence_file.content,
        media_type=(
            evidence_file.content_type
        ),
        headers={
            "Cache-Control":
                "private, no-store",
            "X-Content-Type-Options":
                "nosniff",
        },
    )