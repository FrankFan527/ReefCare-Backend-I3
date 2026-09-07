# ---------------------------------------------------------------------------
# Case decision policy (US5.4).
#
# SECURITY NOTE:
# Recording a response decision begins with an ownership check because the
# case_decision INSERT itself does not independently enforce ownership.
#
# US5.4 starts only AFTER US5.3 has accepted the evidence. Therefore a
# response decision may only be recorded while the case is in
# evidence_accepted.
#
# A successful response decision is non-terminal, but it must still move the
# report into the corresponding canonical non-terminal status so observer
# My Reports, detail and timeline all reflect the persisted decision.
#
# Mapping:
#   monitoring_only       -> monitoring
#   refer_or_share        -> referred
#   intervention_required -> response_recommended
#
# Terminal closure remains the responsibility of US5.5 through
# reefcare_close_report(...).
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import WorkflowError
from app.repositories.case_decision_repository import (
    save_case_decision,
)
from app.repositories.case_repository import (
    change_status,
)
from app.services.case_workflow_service import (
    load_owned_case,
)


# US5.4 begins only after US5.3 has accepted the evidence.
DECISION_READY_STATUS: str = (
    CaseStatus.EVIDENCE_ACCEPTED.value
)


# The three response types defined by US5.4.
#
# no_responsible_partner is deliberately NOT selectable here.
# That value belongs to the US5.5 closure path.
PERMITTED_RESPONSE_TYPES: set[str] = {
    "monitoring_only",
    "refer_or_share",
    "intervention_required",
}


# Every successful US5.4 decision moves the report into a
# canonical non-terminal case status.
#
# This is deliberately a status-code map rather than an
# observer-label map. Observer wording remains owned by the
# case_status table in PostgreSQL.
STATUS_FOR_RESPONSE_TYPE: dict[str, str] = {
    "monitoring_only": (
        CaseStatus.MONITORING.value
    ),
    "refer_or_share": (
        CaseStatus.REFERRED.value
    ),
    "intervention_required": (
        CaseStatus.RESPONSE_RECOMMENDED.value
    ),
}


def validate_response_type(
    response_type: str,
    referred_to: str | None,
) -> None:
    """
    Validate the coordinator's selected US5.4 response type.

    The same values are also validated by
    ResponseTypeDecisionCreate at the HTTP boundary.

    Keeping the validation here protects the service if it
    is later called from another endpoint, test, or internal
    workflow.
    """

    if response_type not in PERMITTED_RESPONSE_TYPES:
        raise WorkflowError(
            "response_type must be one of: "
            + ", ".join(
                sorted(
                    PERMITTED_RESPONSE_TYPES
                )
            )
        )

    if response_type == "refer_or_share":
        if (
            referred_to is None
            or referred_to.strip() == ""
        ):
            raise WorkflowError(
                "referred_to is required when "
                "response_type is refer_or_share"
            )


def validate_case_is_ready_for_a_decision(
    current_status_code: str,
) -> None:
    """
    Enforce the US5.3 -> US5.4 workflow boundary.

    US5.4 explicitly begins only after the evidence has
    been accepted.

    Therefore:
        under_review      -> not ready
        needs_more_info   -> not ready
        evidence_accepted -> ready

    This prevents a coordinator from bypassing the
    evidence usability/credibility assessment.
    """

    if current_status_code != DECISION_READY_STATUS:
        raise WorkflowError(
            "A response decision can only be recorded "
            "after the evidence has been accepted"
        )


async def record_decision(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    response_type: str,
    notes: str | None = None,
    referred_to: str | None = None,
) -> dict:
    """
    Record a US5.4 response-type decision on an owned case
    and move the case into its corresponding non-terminal
    workflow status.

    Workflow:
        ownership check
        -> evidence_accepted state check
        -> response-type validation
        -> save case_decision
        -> move canonical case status
        -> write decision_recorded case_event

    Both writes occur in the same database transaction.
    The API route commits only after this service returns.

    PostgreSQL now() is transaction-scoped, so the
    case_decision.decided_at and case_event.occurred_at
    created during the same transaction use the same
    transaction timestamp.

    The status change is deliberately non-terminal.
    Closing the case still requires US5.5.
    """

    the_case = await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    validate_case_is_ready_for_a_decision(
        current_status_code=the_case[
            "status_code"
        ],
    )

    validate_response_type(
        response_type=response_type,
        referred_to=referred_to,
    )

    # First persist the US5.4 decision.
    the_saved_decision = (
        await save_case_decision(
            db=db,
            report_reference=report_reference,
            coordinator_id=coordinator_id,
            response_type=response_type,
            decision_note=notes,
            referred_to=referred_to,
        )
    )

    # Then move the report into the matching canonical
    # non-terminal status.
    #
    # No observer-facing label is hardcoded here.
    # reefcare_change_status() writes case_event and the
    # observer APIs later obtain case_status.observer_label
    # from PostgreSQL.
    the_target_status = (
        STATUS_FOR_RESPONSE_TYPE[
            response_type
        ]
    )

    await change_status(
        db=db,
        report_reference=report_reference,
        status_code=the_target_status,
        actor_user_id=coordinator_id,
        note=None,
        event_type="decision_recorded",
    )

    return {
        "report_reference":
            report_reference,

        "response_type":
            the_saved_decision[
                "response_type"
            ],

        "decided_at":
            the_saved_decision[
                "decided_at"
            ],

        "decided_by":
            the_saved_decision[
                "coordinator_id"
            ],
    }