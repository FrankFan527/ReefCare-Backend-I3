# ---------------------------------------------------------------------------
# Case closure policy (US5.5, Iteration 2-compatible).
#
# Normal coordinator closure requires a persisted US5.4
# response decision.
#
# The US5.3 not-substantiated assessment is different:
# the evidence assessment itself is the decision-tree
# outcome, so it has a dedicated closure helper that does
# not manufacture an unnecessary US5.4 response decision.
# ---------------------------------------------------------------------------

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    NotFoundError,
    WorkflowError,
)
from app.repositories.case_decision_repository import (
    get_latest_decision,
)
from app.repositories.case_repository import (
    close_report,
    get_closure_reason,
    transition_is_permitted,
)
from app.services.case_workflow_service import (
    load_owned_case,
)


TERMINAL_STATUS_FOR_CLOSURE_REASON: dict[
    str,
    str,
] = {
    "referred_other_org":
        "closed_no_action",

    "monitored_no_action":
        "closed_no_action",

    "not_substantiated":
        "closed_not_substantiated",

    "no_responsible_partner":
        "closed_no_partner",

    "logged_for_reference":
        "closed_logged",

    "resolved_acted_on":
        "closed_resolved",
}


CLOSURE_REASON_FOR_RESPONSE_TYPE: dict[
    str,
    str,
] = {
    "refer_or_share":
        "referred_other_org",

    "monitoring_only":
        "monitored_no_action",

    "no_responsible_partner":
        "no_responsible_partner",
}


NOT_SUBSTANTIATED_REASON = (
    "not_substantiated"
)

NOT_SUBSTANTIATED_STATUS = (
    "closed_not_substantiated"
)

DEFAULT_NOT_SUBSTANTIATED_NOTE = (
    "Could not be confirmed from the evidence provided."
)


async def validate_closure_rules(
    db: AsyncSession,
    closure_reason_code: str,
    public_closure_note: (
        str | None
    ),
) -> dict:
    """
    Confirm the closure reason:

    - exists
    - is currently selectable
    - carries a note when requires_note is true
    """

    reason = await get_closure_reason(
        db=db,
        closure_reason_code=(
            closure_reason_code
        ),
    )

    if reason is None:
        raise NotFoundError(
            "Unknown closure reason: "
            f"{closure_reason_code}"
        )

    if not reason[
        "is_selectable"
    ]:
        raise WorkflowError(
            "Closure reason "
            f"{closure_reason_code} "
            "is not currently selectable"
        )

    if reason[
        "requires_note"
    ]:
        if (
            public_closure_note
            is None
            or
            public_closure_note
            .strip()
            == ""
        ):
            raise WorkflowError(
                "Closure reason "
                f"{closure_reason_code} "
                "requires a closure note"
            )

    return reason


def validate_decision_closure_combination(
    response_type: (
        str | None
    ),
    closure_reason_code: str,
) -> None:
    """
    Prevent a closure reason that contradicts a mapped
    response decision.
    """

    if response_type is None:
        return

    expected_reason = (
        CLOSURE_REASON_FOR_RESPONSE_TYPE
        .get(
            response_type
        )
    )

    if expected_reason is None:
        return

    if (
        expected_reason
        != closure_reason_code
    ):
        raise WorkflowError(
            "A case decided as "
            f"{response_type} "
            "cannot be closed as "
            f"{closure_reason_code}; "
            "expected "
            f"{expected_reason}"
        )


async def close_not_substantiated_from_assessment(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    assessment_note: (
        str | None
    ) = None,
) -> dict:
    """
    Complete the US5.3 Q2=false path.

    The evidence assessment itself is the decision-tree
    outcome, so this path does not require a separate US5.4
    response decision.

    The caller owns the transaction. No commit occurs here,
    allowing:

        assessment row
        + closure decision
        + terminal status
        + case event

    to commit atomically.

    not_substantiated requires a public-safe note in the
    current reference table. Because assessment notes are
    optional in the API contract, a safe default is used
    when the coordinator leaves notes empty.
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

    closure_note = (
        assessment_note.strip()
        if (
            assessment_note
            is not None
            and assessment_note
            .strip()
            != ""
        )
        else
        DEFAULT_NOT_SUBSTANTIATED_NOTE
    )

    await validate_closure_rules(
        db=db,
        closure_reason_code=(
            NOT_SUBSTANTIATED_REASON
        ),
        public_closure_note=(
            closure_note
        ),
    )

    move_is_allowed = (
        await transition_is_permitted(
            db=db,
            from_status_code=(
                case[
                    "status_code"
                ]
            ),
            to_status_code=(
                NOT_SUBSTANTIATED_STATUS
            ),
        )
    )

    if not move_is_allowed:
        raise WorkflowError(
            "A case in "
            f"{case['status_code']} "
            "cannot be closed as "
            f"{NOT_SUBSTANTIATED_REASON}"
        )

    final_status = (
        await close_report(
            db=db,
            report_reference=(
                report_reference
            ),
            coordinator_id=(
                coordinator_id
            ),
            closure_reason_code=(
                NOT_SUBSTANTIATED_REASON
            ),
            terminal_status_code=(
                NOT_SUBSTANTIATED_STATUS
            ),
            note=(
                closure_note
            ),
            referred_to=None,
        )
    )

    return {
        "report_reference":
            report_reference,

        "status":
            final_status,

        "closure_reason_code":
            NOT_SUBSTANTIATED_REASON,
    }


async def close_case(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    closure_reason_code: str,
    public_closure_note: (
        str | None
    ) = None,
    referred_to: (
        str | None
    ) = None,
) -> dict:
    """
    Close an owned case through the normal sanctioned
    closure workflow.

    Unlike the US5.3 assessment-specific helper above,
    this normal endpoint still requires a persisted US5.4
    response decision.
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

    await validate_closure_rules(
        db=db,
        closure_reason_code=(
            closure_reason_code
        ),
        public_closure_note=(
            public_closure_note
        ),
    )

    existing_decision = (
        await get_latest_decision(
            db=db,
            report_reference=(
                report_reference
            ),
        )
    )

    if existing_decision is None:
        raise WorkflowError(
            "A case must have a recorded "
            "decision before it can be closed"
        )

    validate_decision_closure_combination(
        response_type=(
            existing_decision[
                "response_type"
            ]
        ),
        closure_reason_code=(
            closure_reason_code
        ),
    )

    terminal_status_code = (
        TERMINAL_STATUS_FOR_CLOSURE_REASON
        .get(
            closure_reason_code
        )
    )

    if terminal_status_code is None:
        raise WorkflowError(
            "Closure reason "
            f"{closure_reason_code} "
            "has no configured terminal status"
        )

    move_is_allowed = (
        await transition_is_permitted(
            db=db,
            from_status_code=(
                case[
                    "status_code"
                ]
            ),
            to_status_code=(
                terminal_status_code
            ),
        )
    )

    if not move_is_allowed:
        raise WorkflowError(
            "A case in "
            f"{case['status_code']} "
            "cannot be closed as "
            f"{closure_reason_code}, "
            "which would move it to "
            f"{terminal_status_code}"
        )

    final_status_code = (
        await close_report(
            db=db,
            report_reference=(
                report_reference
            ),
            coordinator_id=(
                coordinator_id
            ),
            closure_reason_code=(
                closure_reason_code
            ),
            terminal_status_code=(
                terminal_status_code
            ),
            note=(
                public_closure_note
            ),
            referred_to=(
                referred_to
            ),
        )
    )

    return {
        "report_reference":
            report_reference,

        "status":
            final_status_code,

        "closure_reason_code":
            closure_reason_code,
    }