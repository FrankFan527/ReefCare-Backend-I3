from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import (
    AuthorizationError,
    DatabaseOperationError,
    NotFoundError,
    WorkflowError,
)
from app.repositories.case_decision_repository import (
    get_latest_decision,
)
from app.repositories.case_repository import (
    change_status,
    get_case,
)
from app.repositories.evidence_repository import (
    list_case_evidence_metadata,
)
from app.repositories.location_repository import (
    get_report_location,
)
from app.repositories.report_repository import (
    get_reviewed_ai_suggestions,
)
from app.schemas.case import (
    AIAssistedContext,
    AISuggestionSummary,
)
from app.services.information_service import (
    get_information_exchange,
)
from app.services.projection_service import (
    build_coordinator_case_projection,
)
from app.services.smart_report_service import (
    _FIELD_LABELS,
)


async def get_owned_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Load a case and enforce current coordinator ownership
    before it can be used by a sensitive workflow.
    """

    case = await get_case(
        db=db,
        report_reference=report_reference,
    )

    if case is None:
        raise NotFoundError(
            "Report not found"
        )

    if (
        case["claimed_by_user_id"]
        != coordinator_id
    ):
        raise AuthorizationError(
            "You do not own this case"
        )

    return case


async def get_coordinator_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Build the complete authorised coordinator review
    projection.

    The response contains:
    - report and observation details
    - authorised precise location
    - safe evidence metadata
    - latest saved US5.4 response decision, when one exists
    - what the Observer decided about each AI suggestion

    No decision is a valid state and returns
    latestDecision = null.
    """

    case = await get_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    location = await get_report_location(
        db=db,
        report_reference=report_reference,
        user_id=coordinator_id,
    )

    evidence_rows = (
        await list_case_evidence_metadata(
            db=db,
            report_reference=report_reference,
        )
    )

    latest_decision = (
        await get_latest_decision(
            db=db,
            report_reference=report_reference,
        )
    )

    # US6.3 AC4. Ownership was already established by
    # get_owned_case() above, so the exchange is fetched
    # without repeating the check.
    information_exchange = (
        await get_information_exchange(
            db=db,
            report_reference=report_reference,
        )
    )

    # US5.2. What the Observer decided about each AI suggestion
    # before submitting. Only confirmed and corrected entries are
    # returned: a removed suggestion was rejected by the Observer,
    # so it describes nothing about this report.
    #
    # available is false when a report carries none, which is every
    # report submitted before this was built. The block is still
    # returned rather than omitted, so the interface can state that
    # a report had no AI assistance rather than leaving the
    # Coordinator to infer it from a missing field.
    reviewed_suggestions = (
        await get_reviewed_ai_suggestions(
            db=db,
            report_reference=report_reference,
        )
    )

    ai_assisted = AIAssistedContext(
        available=bool(
            reviewed_suggestions
        ),

        source=(
            "smart_report_structuring"
            if reviewed_suggestions
            else None
        ),

        # Not captured anywhere. The submission contract carries
        # field, value and status, and no timestamp, so there is
        # nothing to return. Substituting the submission time would
        # answer a different question under this label.
        generated_at=None,

        is_unverified_ai_output=True,

        suggestions=[
            AISuggestionSummary(
                field=row["field"],

                # Derived from the Smart Report field map rather
                # than stored, so a wording change lands in one
                # place instead of two.
                label=_FIELD_LABELS.get(
                    row["field"],
                    row["field"],
                ),

                value=row["suggested_value"],

                status=row["status"],
            )
            for row in reviewed_suggestions
        ],
    )

    # US5.2 AC2. US5.6 v2.2 is a separate geographic-analysis API. Fetch optional
    # hotspot-context independently so an analysis failure cannot block review.
    return build_coordinator_case_projection(
        case=case,
        location=location,
        evidence_rows=evidence_rows,
        latest_decision=latest_decision,
        information_exchange=information_exchange,
        ai_assisted=ai_assisted,
    )


async def set_case_under_review(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
):
    """
    Move an owned case from CLAIMED to UNDER_REVIEW.

    Ownership is checked before the workflow transition.

    PostgreSQL reefcare_change_status() remains authoritative
    for the actual status change and audit-event creation.
    """

    case = await get_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    current_status = case[
        "status_code"
    ]

    if (
        current_status
        != CaseStatus.CLAIMED.value
    ):
        raise WorkflowError(
            "A case can only start review "
            "while its status is claimed"
        )

    try:
        new_status = await change_status(
            db=db,
            report_reference=report_reference,
            status_code=(
                CaseStatus.UNDER_REVIEW.value
            ),
            actor_user_id=coordinator_id,
        )

        await db.commit()

        return new_status

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to move case under review"
        ) from exc