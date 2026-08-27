from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.api.dependencies.authorization import (
    CurrentCoordinator,
)
from app.api.dependencies.db import DatabaseSession
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
    EvidenceSummary,
    PreciseLocationResponse,
)
from app.services.case_ownership_service import (
    claim_report_atomically,
    get_current_case_owner,
)
from app.services.case_service import (
    get_authorised_case_location,
    get_case_evidence_metadata,
    get_owned_case,
)
from app.services.queue_service import (
    build_queue_response,
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
    rows, total = await list_incoming_reports(
        db=db,
        page=page,
        page_size=page_size,
    )

    return build_queue_response(
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/reports/{report_id}/claim",
    response_model=ClaimedCaseResponse,
)
async def claim_report(
    report_id: int,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    coordinator_id = current_coordinator[
        "user_id"
    ]

    try:
        report_reference = (
            await claim_report_atomically(
                db=db,
                report_id=report_id,
                coordinator_id=coordinator_id,
            )
        )

        owner = await get_current_case_owner(
            db=db,
            report_id=report_id,
        )

        return ClaimedCaseResponse(
            report_id=owner["report_id"],
            report_reference=report_reference,
            owner=CaseOwnerResponse(
                id=owner["claimed_by_user_id"],
                display_name=owner[
                    "display_name"
                ],
            ),
            status_code=owner["status_code"],
            status_label=owner["status_label"],
            claimed_at=owner["claimed_at"],
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
    "/reports/{report_id}",
    response_model=CoordinatorCaseResponse,
)
async def get_case(
    report_id: int,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    coordinator_id = current_coordinator[
        "user_id"
    ]

    try:
        case = await get_owned_case(
            db=db,
            report_id=report_id,
            coordinator_id=coordinator_id,
        )

        location = (
            await get_authorised_case_location(
                db=db,
                report_reference=case[
                    "report_reference"
                ],
                coordinator_id=coordinator_id,
            )
        )

        evidence_rows = (
            await get_case_evidence_metadata(
                db=db,
                report_id=report_id,
            )
        )

        precise_location = None

        if location is not None:
            precise_location = (
                PreciseLocationResponse(
                    latitude=location["latitude"],
                    longitude=location["longitude"],
                    uncertainty_metres=location[
                        "uncertainty_metres"
                    ],
                    confidence_label=location[
                        "confidence_label"
                    ],
                    source_label=location[
                        "source_label"
                    ],
                    relocation_notes=location[
                        "relocation_notes"
                    ],
                )
            )

        evidence = [
            EvidenceSummary(
                evidence_id=row["evidence_id"],
                media_type=row["media_type"],
                captured_at=row["captured_at"],
                uploaded_at=row["uploaded_at"],
            )
            for row in evidence_rows
        ]

        return CoordinatorCaseResponse(
            report_id=case["report_id"],
            report_reference=case[
                "report_reference"
            ],
            observer_id=case["observer_id"],
            threat=case["threat"],
            description=case["description"],
            estimated_depth_metres=case[
                "estimated_depth_metres"
            ],
            area=case["area"],
            precise_location=precise_location,
            status_code=case["status_code"],
            status_label=case["status_label"],
            submitted_at=case["submitted_at"],
            owner=CaseOwnerResponse(
                id=case["claimed_by_user_id"],
                display_name=case[
                    "claimed_by"
                ],
            ),
            evidence=evidence,
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