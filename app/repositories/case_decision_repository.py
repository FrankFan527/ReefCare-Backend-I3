# ---------------------------------------------------------------------------
# Case decision persistence (US5.3 / US5.4).
#
# Repositories own SQL; services own workflow.
#
# Evidence assessment, response decision and terminal closure may all create
# rows in case_decision. Therefore a "latest response decision" must be
# distinguished from assessment-only and closure rows.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def save_case_decision(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    response_type: str,
    decision_note: str | None = None,
    referred_to: str | None = None,
) -> dict:
    """
    Insert one non-terminal US5.4 response decision.

    closure_reason_id remains NULL because this endpoint
    records the response decision only. Terminal closure is
    handled separately through reefcare_close_report().

    The caller commits.
    """

    the_decision_result = await db.execute(
        text(
            """
            INSERT INTO case_decision
                (
                    report_id,
                    coordinator_id,
                    response_type,
                    decision_note,
                    referred_to
                )
            SELECT
                r.report_id,
                :coordinator_id,
                :response_type,
                :decision_note,
                :referred_to

            FROM report AS r

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

            RETURNING
                case_decision_id,
                response_type,
                decided_at,
                coordinator_id
            """
        ),
        {
            "report_reference":
                report_reference,
            "coordinator_id":
                coordinator_id,
            "response_type":
                response_type,
            "decision_note":
                decision_note,
            "referred_to":
                referred_to,
        },
    )

    return dict(
        the_decision_result
        .mappings()
        .one()
    )


async def get_latest_decision(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Return the newest saved US5.4 response decision.

    case_decision also stores US5.3 evidence assessments
    and US5.5 closure records. Those rows must not replace
    the response decision returned to the coordinator UI.

    A US5.4 response decision is identified by:
    - response_type IS NOT NULL
    - closure_reason_id IS NULL

    Returns None when the report has no saved response
    decision.
    """

    the_decision_result = await db.execute(
        text(
            """
            SELECT
                cd.case_decision_id,
                cd.response_type,
                cd.referred_to,
                cd.decision_note,
                cd.decided_at,
                cd.coordinator_id

            FROM case_decision AS cd

            JOIN report AS r
                ON r.report_id =
                   cd.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

                AND cd.response_type
                    IS NOT NULL

                AND cd.closure_reason_id
                    IS NULL

            ORDER BY
                cd.decided_at DESC,
                cd.case_decision_id DESC

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference
        },
    )

    the_decision_row = (
        the_decision_result
        .mappings()
        .first()
    )

    if the_decision_row is None:
        return None

    return dict(the_decision_row)


async def save_evidence_assessment(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
    evidence_usable: bool,
    observation_credible: bool | None = None,
    decision_note: str | None = None,
) -> dict | None:
    """
    Record a coordinator's answers to the two evidence
    questions (US5.3).

    response_type remains NULL because assessment is not a
    US5.4 response decision.

    The caller commits.
    """

    the_assessment_result = await db.execute(
        text(
            """
            INSERT INTO case_decision
                (
                    report_id,
                    coordinator_id,
                    evidence_usable,
                    observation_credible,
                    decision_note
                )
            SELECT
                r.report_id,
                :coordinator_id,
                :evidence_usable,
                :observation_credible,
                :decision_note

            FROM report AS r

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at IS NULL

            RETURNING
                case_decision_id,
                evidence_usable,
                observation_credible,
                decided_at,
                coordinator_id
            """
        ),
        {
            "report_reference":
                report_reference,
            "coordinator_id":
                coordinator_id,
            "evidence_usable":
                evidence_usable,
            "observation_credible":
                observation_credible,
            "decision_note":
                decision_note,
        },
    )

    the_assessment_row = (
        the_assessment_result
        .mappings()
        .first()
    )

    if the_assessment_row is None:
        return None

    return dict(the_assessment_row)