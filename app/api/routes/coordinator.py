from datetime import datetime

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
    CoordinatorHistoryItem,
    CoordinatorHistoryResponse,
    CoordinatorQueueResponse,
    ReferralHistoryEntry,
    StartReviewResponse,
)
from app.services.case_history_service import (
    get_closed_case_history,
)

from app.services.case_ownership_service import (
    claim_report as claim_report_service,
)
from app.services.case_service import (
    get_coordinator_case,
    set_case_under_review,
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
    Return the active coordinator queue.

    Authentication and coordinator-role checks are enforced
    through CurrentCoordinator.

    The queue contains active submitted reports and exposes
    only queue-safe general information, current status and
    ownership details.

    Precise coordinates and private evidence are excluded.
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


@router.post(
    "/reports/{report_reference}/start-review",
    response_model=StartReviewResponse,
)
async def start_case_review(
    report_reference: str,
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
):
    """
    Start reviewing a claimed case.

    Only the coordinator who currently owns the case may
    perform this action.

    The service moves the report from CLAIMED to
    UNDER_REVIEW through reefcare_change_status().
    """

    coordinator_id = current_coordinator[
        "user_id"
    ]

    new_status = await set_case_under_review(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    return StartReviewResponse(
        report_reference=report_reference,
        status_code=new_status,
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



# ---------------------------------------------------------------------------
# US5.8 Closed case and referral history.
#
# Registered on /cases/history rather than under /reports, because it returns a
# filtered set rather than one report. It cannot collide with
# /reports/{report_reference}: the path segments differ.
#
# Ownership is enforced inside the repository query rather than here. There is
# no single case to check, so both queries filter on claimed_by_user_id and a
# case the coordinator does not own is never selected in the first place.
# ---------------------------------------------------------------------------


@router.get(
    "/cases/history",
    response_model=CoordinatorHistoryResponse,
)
async def get_case_history(
    current_coordinator: CurrentCoordinator,
    db: DatabaseSession,
    closure_reason: str | None = Query(
        default=None,
        description=(
            "Filter by closure_reason.code, for example "
            "referred_other_org"
        ),
    ),
    threat_category: str | None = Query(
        default=None,
        description=(
            "Filter by threat_category.code, for example "
            "ghost_gear"
        ),
    ),
    closed_from: datetime | None = Query(
        default=None,
        description=(
            "Only cases closed on or after this time"
        ),
    ),
    closed_to: datetime | None = Query(
        default=None,
        description=(
            "Only cases closed strictly before this time"
        ),
    ),
    was_referred: bool | None = Query(
        default=None,
        description=(
            "true returns only cases with a recorded "
            "referral, false only those without"
        ),
    ),
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
    Return the coordinator's own closed cases, newest closure first.

    US5.8 AC1 makes filtering the way a coordinator reaches their history, so
    every filter is optional and absent means unfiltered rather than empty.

    No owner filter. The endpoint is already scoped to the authenticated
    coordinator, so the parameter could only do nothing or widen access.

    Read only: no commit, and nothing here writes.
    """

    # the coordinator comes from the verified token, never from a query
    # parameter
    the_coordinator_id = current_coordinator[
        "user_id"
    ]

    the_history = await get_closed_case_history(
        db=db,
        coordinator_id=the_coordinator_id,
        closure_reason_code=closure_reason,
        threat_code=threat_category,
        closed_from=closed_from,
        closed_to=closed_to,
        was_referred=was_referred,
        page=page,
        page_size=page_size,
    )

    the_items = [
        CoordinatorHistoryItem(
            report_reference=the_item[
                "report_reference"
            ],
            threat=the_item["threat"],
            area=the_item["area"],
            status_code=the_item[
                "status_code"
            ],
            status_label=the_item[
                "status_label"
            ],
            submitted_at=the_item[
                "submitted_at"
            ],
            closed_at=the_item["closed_at"],
            closure_reason_code=the_item[
                "closure_reason_code"
            ],
            closure_reason_label=the_item[
                "closure_reason_label"
            ],
            closure_note=the_item[
                "closure_note"
            ],
            referrals=[
                ReferralHistoryEntry(
                    referred_to=the_referral[
                        "referred_to"
                    ],
                    decided_at=the_referral[
                        "decided_at"
                    ],
                    note=the_referral[
                        "decision_note"
                    ],
                    decided_by_name=the_referral[
                        "decided_by_name"
                    ],
                )
                for the_referral in the_item[
                    "referrals"
                ]
            ],
        )
        for the_item in the_history["items"]
    ]

    return CoordinatorHistoryResponse(
        items=the_items,
        page=the_history["page"],
        page_size=the_history["page_size"],
        total=the_history["total"],
        filters_applied=the_history[
            "filters_applied"
        ],
    )