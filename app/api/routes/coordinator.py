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
    CoordinatorHistoryFilters,
    CoordinatorHistoryItem,
    CoordinatorHistoryResponse,
    CoordinatorQueueResponse,
    HistoryCodeLabel,
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
        le=10_000,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        alias="pageSize",
    ),
):
    """
    Return the active coordinator queue.

    Authentication and coordinator-role checks are enforced
    through CurrentCoordinator.

    Unclaimed received reports remain visible to all
    coordinators.

    Once a report has been claimed, non-terminal workflow
    states remain visible only to the coordinator who
    currently owns the case.

    Iteration 2 action-stage cases remain active through
    response_planned and response_complete until an
    explicit terminal closure succeeds.

    Precise coordinates and private evidence are excluded.
    """

    coordinator_id = current_coordinator[
        "user_id"
    ]

    return await list_incoming_reports(
        db=db,
        coordinator_id=coordinator_id,
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

    Terminal cases remain readable by their current owner,
    which supports closed-case history drill-through.
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
# US5.8 / API-10 Closed case and referral history.
#
# Registered on /cases/history because this route returns a
# filtered collection rather than one report.
#
# Ownership is enforced inside the repository query:
# report.claimed_by_user_id must match the authenticated
# coordinator.
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
        alias="closureReason",
        description=(
            "Filter by closure_reason.code, for example "
            "referred_other_org"
        ),
    ),
    threat_category: str | None = Query(
        default=None,
        alias="threatCategory",
        description=(
            "Filter by threat_category.code, for example "
            "ghost_gear"
        ),
    ),
    closed_from: datetime | None = Query(
        default=None,
        alias="closedFrom",
        description=(
            "Only cases closed on or after this time"
        ),
    ),
    closed_to: datetime | None = Query(
        default=None,
        alias="closedTo",
        description=(
            "Only cases closed strictly before this time"
        ),
    ),
    was_referred: bool | None = Query(
        default=None,
        alias="wasReferred",
        description=(
            "true returns only cases with a recorded "
            "referral; false only cases without one"
        ),
    ),
    page: int = Query(
        default=1,
        ge=1,
        le=10_000,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        alias="pageSize",
    ),
):
    """
    Return the authenticated coordinator's own closed cases.

    All filters are optional.

    No owner parameter is accepted. The authenticated
    coordinator identity is always taken from the verified
    token.

    This route is read only.
    """

    coordinator_id = current_coordinator[
        "user_id"
    ]

    history = await get_closed_case_history(
        db=db,
        coordinator_id=coordinator_id,
        closure_reason_code=closure_reason,
        threat_code=threat_category,
        closed_from=closed_from,
        closed_to=closed_to,
        was_referred=was_referred,
        page=page,
        page_size=page_size,
    )

    items = []

    for item in history["items"]:
        closure_reason_model = None

        if (
            item["closure_reason_code"]
            is not None
        ):
            closure_reason_model = (
                HistoryCodeLabel(
                    code=item[
                        "closure_reason_code"
                    ],
                    label=item[
                        "closure_reason_label"
                    ],
                )
            )

        items.append(
            CoordinatorHistoryItem(
                report_reference=item[
                    "report_reference"
                ],
                threat_category=(
                    HistoryCodeLabel(
                        code=item[
                            "threat_code"
                        ],
                        label=item[
                            "threat"
                        ],
                    )
                ),
                general_location=item[
                    "area"
                ],
                status=HistoryCodeLabel(
                    code=item[
                        "status_code"
                    ],
                    label=item[
                        "status_label"
                    ],
                ),
                submitted_at=item[
                    "submitted_at"
                ],
                closed_at=item[
                    "closed_at"
                ],
                closure_reason=(
                    closure_reason_model
                ),
                closure_note=item[
                    "closure_note"
                ],
                was_referred=item[
                    "was_referred"
                ],
                referrals=[
                    ReferralHistoryEntry(
                        referred_to=referral[
                            "referred_to"
                        ],
                        referred_at=referral[
                            "referred_at"
                        ],
                        note=referral[
                            "decision_note"
                        ],
                        decided_by_name=(
                            referral[
                                "decided_by_name"
                            ]
                        ),
                    )
                    for referral
                    in item["referrals"]
                ],
            )
        )

    return CoordinatorHistoryResponse(
        items=items,
        page=history["page"],
        page_size=history[
            "page_size"
        ],
        total=history["total"],
        applied_filters=(
            CoordinatorHistoryFilters(
                **history[
                    "applied_filters"
                ]
            )
        ),
    )