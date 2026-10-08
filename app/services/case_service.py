from sqlalchemy.exc import (
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.enums import (
    CaseStatus,
)
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


def _summarise_ai_sources(
    reviewed_suggestions,
) -> str | None:
    """
    Build a safe block-level provenance summary.

    Individual AISuggestionSummary.source values remain the
    authoritative source information.

    The block-level source exists for compatibility with
    clients that already consume aiAssisted.source.

    Returns:

        smart_report
        visual_recognition
        mixed
        None
    """

    sources = {
        row["source"]
        for row
        in reviewed_suggestions
        if (
            row.get(
                "source"
            )
            is not None
        )
    }

    if not sources:
        return None

    if len(sources) == 1:
        return next(
            iter(
                sources
            )
        )

    return "mixed"


def _build_ai_assisted_context(
    reviewed_suggestions,
) -> AIAssistedContext:
    """
    Build the Coordinator-facing AI assistance projection.

    QA-AI-01:
    Smart Report and Visual Recognition provenance is kept
    at suggestion level instead of labelling every AI value
    as Smart Report.

    Removed suggestions are already excluded by the
    repository because the Observer rejected them.
    """

    return AIAssistedContext(
        available=bool(
            reviewed_suggestions
        ),

        source=(
            _summarise_ai_sources(
                reviewed_suggestions
            )
        ),

        # AI generation time is not persisted.
        generated_at=None,

        is_unverified_ai_output=True,

        suggestions=[
            AISuggestionSummary(
                field=row[
                    "field"
                ],

                label=(
                    _FIELD_LABELS.get(
                        row[
                            "field"
                        ],
                        row[
                            "field"
                        ],
                    )
                ),

                value=row[
                    "suggested_value"
                ],

                status=row[
                    "status"
                ],

                source=row[
                    "source"
                ],

                confidence=row[
                    "confidence"
                ],
            )
            for row
            in reviewed_suggestions
        ],
    )


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
    - Observer-reviewed AI suggestions with per-suggestion
      source provenance

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

    # US6.3 AC4.
    #
    # Ownership was already established by get_owned_case()
    # above, so the exchange can be fetched without
    # repeating the ownership check.
    information_exchange = (
        await get_information_exchange(
            db=db,
            report_reference=report_reference,
        )
    )

    # US5.2 / QA-AI-01.
    #
    # The repository returns only confirmed/corrected
    # suggestions and already includes source + confidence.
    #
    # A removed suggestion was rejected by the Observer and
    # therefore is not shown as report context.
    reviewed_suggestions = (
        await get_reviewed_ai_suggestions(
            db=db,
            report_reference=report_reference,
        )
    )

    ai_assisted = (
        _build_ai_assisted_context(
            reviewed_suggestions
        )
    )

    # US5.2 AC2.
    #
    # Hotspot/context analysis remains independent so a
    # failure there cannot block the core review projection.
    return build_coordinator_case_projection(
        case=case,
        location=location,
        evidence_rows=evidence_rows,
        latest_decision=latest_decision,
        information_exchange=(
            information_exchange
        ),
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

    PostgreSQL reefcare_change_status() remains
    authoritative for the actual status change and
    audit-event creation.
    """

    case = await get_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    current_status = (
        case[
            "status_code"
        ]
    )

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
                CaseStatus
                .UNDER_REVIEW
                .value
            ),
            actor_user_id=(
                coordinator_id
            ),
        )

        await db.commit()

        return new_status

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to move case under review"
        ) from exc