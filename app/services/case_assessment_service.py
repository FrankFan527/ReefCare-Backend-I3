# ---------------------------------------------------------------------------
# Evidence assessment workflow (US5.3).
#
# Q1  Is the evidence usable?
# Q2  Is the observation credible?
#
# Outcomes:
#
# under_review
#   -> needs_more_info
#   -> evidence_accepted
#   -> closed_not_substantiated
#
# The final outcome is a terminal closure, but it is part
# of the evidence-assessment decision tree and therefore
# does not require a separate US5.4 response decision.
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    DatabaseOperationError,
    WorkflowStateError,
)
from app.repositories.case_decision_repository import (
    save_evidence_assessment,
)
from app.repositories.case_repository import (
    change_status,
)
from app.services.case_closure_service import (
    close_not_substantiated_from_assessment,
)
from app.services.case_workflow_service import (
    load_owned_case,
    request_more_information,
    validate_status_transition,
)


STATUS_THAT_MAY_BE_ASSESSED = (
    "under_review"
)

EVIDENCE_ACCEPTED_STATUS = (
    "evidence_accepted"
)

INSUFFICIENT_EVIDENCE_REASON = (
    "The evidence provided could not be used to assess "
    "this report. Please add a clearer photograph or "
    "more detail."
)


def validate_case_is_ready_for_assessment(
    current_status_code: str,
) -> None:
    """
    Only an under-review case may receive a new evidence
    assessment.

    The current status is attached to the 409 response so
    the frontend can recover safely from stale requests.
    """

    if (
        current_status_code
        != STATUS_THAT_MAY_BE_ASSESSED
    ):
        raise WorkflowStateError(
            message=(
                "Evidence can only be assessed while "
                "the case is "
                f"{STATUS_THAT_MAY_BE_ASSESSED}; "
                "this case is "
                f"{current_status_code}"
            ),
            current_status=(
                current_status_code
            ),
        )


async def record_evidence_assessment(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    evidence_usable: bool,
    observation_credible: (
        bool | None
    ) = None,
    notes: (
        str | None
    ) = None,
) -> dict:
    """
    Record the evidence assessment and apply its workflow
    outcome.

    No commit occurs in this service. The route commits
    only after the complete operation succeeds, making the
    assessment and resulting workflow move atomic.
    """

    case = await load_owned_case(
        db=db,
        report_reference=(
            report_reference
        ),
        coordinator_id=(
            coordinator_id
        ),
    )

    validate_case_is_ready_for_assessment(
        current_status_code=(
            case[
                "status_code"
            ]
        ),
    )

    # Q1 = no.
    if not evidence_usable:
        assessment = (
            await save_evidence_assessment(
                db=db,
                report_reference=(
                    report_reference
                ),
                coordinator_id=(
                    coordinator_id
                ),
                evidence_usable=False,
                observation_credible=None,
                decision_note=notes,
            )
        )

        if assessment is None:
            raise DatabaseOperationError(
                "The evidence assessment "
                "could not be recorded"
            )

        result = (
            await request_more_information(
                db=db,
                report_reference=(
                    report_reference
                ),
                coordinator_id=(
                    coordinator_id
                ),
                reason=(
                    notes
                    if notes
                    else
                    INSUFFICIENT_EVIDENCE_REASON
                ),
            )
        )

        return {
            "report_reference":
                report_reference,

            "evidence_usable":
                False,

            "observation_credible":
                None,

            "status":
                result[
                    "status"
                ],

            "assessed_at":
                assessment[
                    "decided_at"
                ],

            "assessed_by":
                assessment[
                    "coordinator_id"
                ],
        }

    assessment = (
        await save_evidence_assessment(
            db=db,
            report_reference=(
                report_reference
            ),
            coordinator_id=(
                coordinator_id
            ),
            evidence_usable=True,
            observation_credible=(
                observation_credible
            ),
            decision_note=notes,
        )
    )

    if assessment is None:
        raise DatabaseOperationError(
            "The evidence assessment "
            "could not be recorded"
        )

    # Q2 = no.
    #
    # This is the API-16 path. It deliberately bypasses
    # the normal US5.5 "response decision required"
    # precondition, because the evidence assessment itself
    # is the not-substantiated decision-tree outcome.
    if observation_credible is False:
        closure = (
            await close_not_substantiated_from_assessment(
                db=db,
                report_reference=(
                    report_reference
                ),
                coordinator_id=(
                    coordinator_id
                ),
                assessment_note=(
                    notes
                ),
            )
        )

        return {
            "report_reference":
                report_reference,

            "evidence_usable":
                True,

            "observation_credible":
                False,

            "status":
                closure[
                    "status"
                ],

            "assessed_at":
                assessment[
                    "decided_at"
                ],

            "assessed_by":
                assessment[
                    "coordinator_id"
                ],
        }

    # Q2 = yes.
    await validate_status_transition(
        db=db,
        from_status_code=(
            case[
                "status_code"
            ]
        ),
        to_status_code=(
            EVIDENCE_ACCEPTED_STATUS
        ),
    )

    new_status = await change_status(
        db=db,
        report_reference=(
            report_reference
        ),
        status_code=(
            EVIDENCE_ACCEPTED_STATUS
        ),
        actor_user_id=(
            coordinator_id
        ),
        note=notes,
        event_type=(
            "decision_recorded"
        ),
    )

    return {
        "report_reference":
            report_reference,

        "evidence_usable":
            True,

        "observation_credible":
            True,

        "status":
            new_status,

        "assessed_at":
            assessment[
                "decided_at"
            ],

        "assessed_by":
            assessment[
                "coordinator_id"
            ],
    }