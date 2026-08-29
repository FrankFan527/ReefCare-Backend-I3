from fastapi import (
    APIRouter,
    Query,
)

from app.api.dependencies.authorization import (
    CurrentCoordinator,
)
from app.api.dependencies.db import (
    DatabaseSession,
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
    """
    Return the coordinator queue.

    Authentication and coordinator-role checks are enforced
    through CurrentCoordinator.

    Queue data is retrieved through the service/repository
    path backed by v_unclaimed_queue.
    """

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
    """
    Claim an unowned report.

    PostgreSQL reefcare_claim_report() remains responsible
    for atomic ownership and claim-event creation.
    """

    coordinator_id = current_coordinator[
        "user_id"
    ]

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


@router.get(
    "/reports/{report_reference}",
    response_model=CoordinatorCaseResponse,
)
async def get_case(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Return the authorised coordinator case-review view.

    The service verifies that the authenticated coordinator
    currently owns the case before sensitive information is
    returned.
    """

    coordinator_id = current_coordinator[
        "user_id"
    ]

    return await get_coordinator_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )