# ---------------------------------------------------------------------------
# US8.1 Coordinator site history — persistence.
#
# A projection, not a table. Backend doc Appendix B: "prefer projection or
# service over duplicating all source data". Everything below reads the
# canonical report, case_decision and case_action rows.
#
# A report belongs to a site through its dive session:
#
#     report -> dive_session -> dive_site
#
# report_location is deliberately never joined here. The site history is
# built at the configured-site level, so no report coordinate is read, let
# alone returned.
# ---------------------------------------------------------------------------

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


# a report that never reached intake is not part of a site's history
THE_PRE_INTAKE_STATUS_CODES: tuple[str, ...] = ("draft", "submitted")


# Status groupings used only where no decision has been recorded. Once a
# decision exists, observation_credible decides, because a case can be closed
# without its evidence ever having been accepted.
THE_STATUS_TO_ASSESSMENT_STATE: str = """
    CASE
        WHEN cs.code IN ('received', 'claimed')             THEN 'not_yet_assessed'
        WHEN cs.code IN ('under_review', 'needs_more_info') THEN 'under_review'
        WHEN cs.code = 'closed_not_substantiated'           THEN 'not_substantiated'
        WHEN cs.is_terminal                                 THEN 'closed_without_assessment'
        ELSE 'evidence_accepted'
    END
"""


async def get_site_identity(
    db: AsyncSession,
    dive_site_id: int,
) -> dict | None:
    the_result = await db.execute(
        text(
            """
            SELECT dive_site_id, name AS site_name, public_area_label
            FROM dive_site
            WHERE dive_site_id = :dive_site_id
            """
        ),
        {"dive_site_id": dive_site_id},
    )

    the_row = the_result.mappings().first()

    return dict(the_row) if the_row is not None else None


async def list_site_observations(
    db: AsyncSession,
    dive_site_id: int,
    coordinator_id: int,
) -> list[dict]:
    """
    Eligible observations at one site, with the assessment state each one has
    actually reached.

    A case in a terminal status always reports a closed state: not
    substantiated, closed after assessment, or closed without assessment.

    The decision used is the most recent one that answered the credibility
    question, which is what Iteration 2 records when a Coordinator accepts or
    rejects evidence. Where no such decision exists the status grouping is
    used instead, and a closed case with no decision is reported as closed
    without assessment rather than as accepted.
    """

    the_result = await db.execute(
        text(
            f"""
            SELECT
                r.report_reference,
                (r.claimed_by_user_id = :coordinator_id) AS owned_by_you,

                tc.code  AS threat_category_code,
                tc.label AS threat_category_label,

                r.observed_at,
                r.submitted_at,

                CASE
                    -- QA-E8-01: a closed case reports its closed state, never
                    -- "Evidence accepted", even if its evidence was accepted
                    -- before it was closed
                    WHEN cs.is_terminal
                         AND (assessed.observation_credible IS FALSE
                              OR cs.code = 'closed_not_substantiated')
                                                                THEN 'not_substantiated'
                    WHEN cs.is_terminal
                         AND assessed.observation_credible IS TRUE THEN 'closed'
                    WHEN assessed.observation_credible IS TRUE  THEN 'evidence_accepted'
                    WHEN assessed.observation_credible IS FALSE THEN 'not_substantiated'
                    ELSE {THE_STATUS_TO_ASSESSMENT_STATE}
                END AS assessment_state,

                -- the Coordinator-facing wording of the closed state
                cs.internal_label AS case_status_label

            FROM report AS r
            JOIN dive_session AS dsn   ON dsn.dive_session_id = r.dive_session_id
            JOIN threat_category AS tc ON tc.threat_category_id = r.threat_category_id
            JOIN case_status AS cs     ON cs.case_status_id = r.current_status_id

            LEFT JOIN LATERAL (
                SELECT cd.observation_credible
                FROM case_decision AS cd
                WHERE cd.report_id = r.report_id
                  AND cd.observation_credible IS NOT NULL
                ORDER BY cd.decided_at DESC, cd.case_decision_id DESC
                LIMIT 1
            ) AS assessed ON TRUE

            WHERE dsn.dive_site_id = :dive_site_id
              AND r.deleted_at IS NULL
              AND cs.code NOT IN :pre_intake_codes

            ORDER BY r.observed_at, r.report_id
            """
        ).bindparams(bindparam("pre_intake_codes", expanding=True)),
        {
            "dive_site_id": dive_site_id,
            "coordinator_id": coordinator_id,
            "pre_intake_codes": list(THE_PRE_INTAKE_STATUS_CODES),
        },
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]


async def list_site_follow_ups(
    db: AsyncSession,
    dive_site_id: int,
    coordinator_id: int,
) -> list[dict]:
    """
    E7 follow-up, monitoring and sourced-outcome records for reports at one
    site.

    Superseded records are excluded: a corrected record should appear once,
    in its current form. Demonstration rows are excluded so seeded content
    never reads as real conservation history.

    notes are not selected. A Coordinator's internal note belongs to the case,
    not to a site-wide view that other Coordinators can open.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,
                (r.claimed_by_user_id = :coordinator_id) AS owned_by_you,

                ca.follow_up_type,
                ca.action_state AS follow_up_state,

                ca.action_date,
                ca.responsible_team,
                ca.recorded_outcome,

                mc.code  AS condition_code,
                mc.label AS condition_label,

                ca.next_follow_up_required,
                ca.next_follow_up_date,

                ca.created_at

            FROM case_action AS ca
            JOIN report AS r          ON r.report_id = ca.report_id
            JOIN dive_session AS dsn  ON dsn.dive_session_id = r.dive_session_id
            LEFT JOIN monitoring_condition AS mc
                                      ON mc.monitoring_condition_id = ca.monitoring_condition_id

            WHERE dsn.dive_site_id = :dive_site_id
              AND r.deleted_at IS NULL
              AND NOT ca.is_demonstration
              AND NOT EXISTS (
                    SELECT 1 FROM case_action AS later
                    WHERE later.supersedes_case_action_id = ca.case_action_id
                  )

            ORDER BY ca.action_date NULLS LAST, ca.created_at, ca.case_action_id
            """
        ),
        {
            "dive_site_id": dive_site_id,
            "coordinator_id": coordinator_id,
        },
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]
