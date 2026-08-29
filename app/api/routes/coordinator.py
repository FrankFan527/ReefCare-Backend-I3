from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies.authorization import (
    CurrentCoordinator,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
)
from app.schemas.case import (
    CaseOwnerResponse,
    ClaimedCaseResponse,
    CoordinatorCaseResponse,
    CoordinatorQueueResponse,
)
from app.services.case_ownership_service import (
    claim_report as claim_report_service,
)
from app.services.case_service import (
    get_coordinator_case,
)
from app.services.queue_service import (
    list_incoming_reports,
)


router = APIRouter()


@router.get(
    "/queue",
    response_model=CoordinatorQueueResponse,
)
async def get_queue(
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
):
    return await list_incoming_reports(
        db=db,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/reports/{report_reference}/claim",
    response_model=ClaimedCaseResponse,
)
async def claim_report(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    coordinator_id = current_coordinator[
        "user_id"
    ]

    try:
        owner = await claim_report_service(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
        )

        return ClaimedCaseResponse(
            report_reference=owner[
                "report_reference"
            ],
            owner=CaseOwnerResponse(
                id=owner[
                    "claimed_by_user_id"
                ],
                display_name=owner[
                    "display_name"
                ],
            ),
            status_code=owner[
                "status_code"
            ],
            status_label=owner[
                "status_label"
            ],
            claimed_at=owner[
                "claimed_at"
            ],
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to claim report",
        ) from exc


@router.get(
    "/reports/{report_reference}",
    response_model=CoordinatorCaseResponse,
)
async def get_case(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    coordinator_id = current_coordinator[
        "user_id"
    ]

    try:
        return await get_coordinator_case(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc