# ---------------------------------------------------------------------------
# US8.2 / US2.4 public-safe site context — persistence.
#
# The eligibility rule lives in these queries rather than in the service, so
# a private field cannot reach a caller through a projection that forgot to
# drop it: the rows returned here never contain one.
#
# What is deliberately never selected:
#   report_reference, observer_id, description, evidence, report_location,
#   claimed_by_user_id, decision_note, closure_reason
#
# What makes an observation publishable: a Coordinator recorded a decision
# accepting its evidence. Status alone is not enough, because a case can be
# closed without its evidence ever having been accepted.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_public_site_identity(
    db: AsyncSession,
    dive_site_id: int,
) -> dict | None:
    """
    Published reference data for one site. No coordinate is read here: the
    public context is a summary, and the site's own coordinate is served by
    the existing E2 site endpoint where it belongs.
    """

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


async def summarise_accepted_threats(
    db: AsyncSession,
    dive_site_id: int,
) -> list[dict]:
    """
    Accepted observations at one site, grouped by threat category.

    Recency is returned at month precision. An exact date at a quiet site
    could identify one dive and through it one diver, which AC3 rules out as
    surely as returning the report itself.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                tc.code  AS threat_category_code,
                tc.label AS threat_category_label,
                count(*) AS accepted_report_count,
                to_char(max(r.observed_at), 'YYYY-MM') AS most_recent_month

            FROM report AS r
            JOIN dive_session AS dsn   ON dsn.dive_session_id = r.dive_session_id
            JOIN threat_category AS tc ON tc.threat_category_id = r.threat_category_id
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
              AND assessed.observation_credible IS TRUE

            GROUP BY tc.code, tc.label, tc.display_order
            ORDER BY tc.display_order, tc.code
            """
        ),
        {"dive_site_id": dive_site_id},
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]


async def count_observations_by_assessment(
    db: AsyncSession,
    dive_site_id: int,
) -> dict:
    """
    Two counts: observations whose evidence was accepted, and observations
    still being reviewed.

    Reports that were reviewed and not substantiated are counted in neither.
    Publishing them would broadcast a rejected claim about a site.
    """

    the_result = await db.execute(
        text(
            """
            SELECT
                count(*) FILTER (
                    WHERE assessed.observation_credible IS TRUE
                ) AS accepted_observations,

                count(*) FILTER (
                    WHERE assessed.observation_credible IS NULL
                      AND cs.code IN ('received', 'claimed',
                                      'under_review', 'needs_more_info')
                ) AS observations_under_review

            FROM report AS r
            JOIN dive_session AS dsn ON dsn.dive_session_id = r.dive_session_id
            JOIN case_status AS cs   ON cs.case_status_id = r.current_status_id
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
            """
        ),
        {"dive_site_id": dive_site_id},
    )

    return dict(the_result.mappings().one())


async def list_publishable_activity(
    db: AsyncSession,
    dive_site_id: int,
    include_follow_ups: bool = True,
) -> list[dict]:
    """
    Conservation and monitoring activity approved for publication, from both
    sources, newest first.

    public_reef_activity carries curated entries. case_action contributes
    only where a Coordinator set is_publishable, which stays false by default
    until the team agrees the E8 eligibility rule.

    include_follow_ups is false for the Iteration 2 /activity endpoint, whose
    published contract carries a curated activity id. Both callers share this
    one eligibility rule either way, which is what US8.2 AC5 asks for.

    The follow-up text published is the recorded outcome, never the internal
    notes, and no report reference travels with it.
    """

    the_result = await db.execute(
        text(
            """
            SELECT activity_id, activity_type, title, summary,
                   activity_date, source_label
            FROM (
                SELECT
                    pra.public_activity_id AS activity_id,
                    pra.activity_type,
                    pra.title,
                    pra.summary,
                    pra.activity_date,
                    pra.source_label,
                    pra.display_order,
                    pra.public_activity_id AS tiebreak
                FROM public_reef_activity AS pra
                WHERE pra.dive_site_id = :dive_site_id
                  AND pra.is_public IS TRUE

                UNION ALL

                SELECT
                    NULL::bigint AS activity_id,
                    at.code AS activity_type,
                    at.label AS title,
                    ca.recorded_outcome AS summary,
                    ca.action_date AS activity_date,
                    coalesce(ca.responsible_team, 'ReefCare MY') AS source_label,
                    50 AS display_order,
                    ca.case_action_id AS tiebreak
                FROM case_action AS ca
                JOIN report AS r         ON r.report_id = ca.report_id
                JOIN dive_session AS dsn ON dsn.dive_session_id = r.dive_session_id
                JOIN action_type AS at   ON at.action_type_id = ca.action_type_id
                WHERE :include_follow_ups
                  AND dsn.dive_site_id = :dive_site_id
                  AND r.deleted_at IS NULL
                  AND ca.is_publishable IS TRUE
                  AND NOT ca.is_demonstration
                  AND ca.recorded_outcome IS NOT NULL
                  AND NOT EXISTS (
                        SELECT 1 FROM case_action AS later
                        WHERE later.supersedes_case_action_id = ca.case_action_id
                      )
            ) AS the_publishable
            ORDER BY activity_date DESC NULLS LAST, display_order, tiebreak DESC
            """
        ),
        {
            "dive_site_id": dive_site_id,
            "include_follow_ups": include_follow_ups,
        },
    )

    return [dict(the_row) for the_row in the_result.mappings().all()]
