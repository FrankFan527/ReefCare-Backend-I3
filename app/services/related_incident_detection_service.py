# ---------------------------------------------------------------------------
# US5.9 Related Incident Detection — ENGINE.
#
# OWNER: HongShen (matching logic, similarity signals, relatedness results).
# Scaffold created by Miusan so the engine plugs into the agreed data
# contract. HongShen may restructure this file freely, as long as the three
# rules below hold.
#
# RULES OF THE BOUNDARY
#
#   1. Read and write ONLY through related_incident_repository.py:
#        read  -> get_report_comparison_facts, list_candidate_comparison_facts
#        write -> begin_detection_run, save_detection_candidates,
#                 finish_detection_run
#      No SQL in this file. Schema changes go through Miusan (backend doc §5).
#
#   2. Return suggestions only. The engine never links reports, claims them,
#      changes status or closes anything (US5.9 AC1, AC8). Coordinators
#      decide in related_incident_service.py.
#
#   3. Never block or break submission (AC1) or review (AC9). The entry
#      points below catch everything, mark the run failed and return. A
#      failed run is shown to Coordinators as "analysis unavailable".
#
# PRIVACY
#
#   ReportComparisonFacts.description is for comparison only. Never copy it
#   (or any part of it) into a signal detail, a log message or an exception.
#   Locations arrive already generalised to ~110 m.
#
# HOW FRANK TRIGGERS IT (E4, after a successful submission)
#
#   background_tasks.add_task(
#       run_related_incident_detection_in_background,
#       the_saved_report_reference,
#   )
#
#   The background variant opens its own DB session, because the request
#   session is closed by the time a FastAPI background task runs.
# ---------------------------------------------------------------------------

import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.repositories import related_incident_repository as the_repository
from app.schemas.related_incident import (
    DetectionOutcome,
    DetectionRunState,
    ReportComparisonFacts,
)


logger = logging.getLogger(__name__)


# HONGSHEN: replace with the real version, e.g. "rid-v1", and bump it
# whenever the matching rules change. Runs are keyed on (report, version),
# so a new version re-analyses reports without overwriting the old results.
RULE_VERSION: str = "rid-scaffold"


# HONGSHEN: the observation window searched either side of the source
# report's observed_at. Tune as part of the matching design.
CANDIDATE_WINDOW: timedelta = timedelta(days=30)

# upper bound on reports compared per run, so one call stays cheap
CANDIDATE_POOL_LIMIT: int = 200


async def match_related_reports(
    the_source: ReportComparisonFacts,
    the_pool: list[ReportComparisonFacts],
) -> DetectionOutcome:
    """
    HONGSHEN: implement the matching here.

    Input
        the_source  the newly submitted report
        the_pool    eligible existing reports within CANDIDATE_WINDOW

    Output
        DetectionOutcome(run_state=COMPLETED, candidates=[...]) when the
        comparison ran (an empty list is a valid "no match" result), or
        DetectionOutcome(run_state=INSUFFICIENT_INFORMATION) when the source
        report lacks enough information to compare at all.

    Each CandidateMatch needs:
        candidate_report_id   from the pool
        relatedness_level     RelatednessLevel.HIGH / MEDIUM / LOW
        signals               [CandidateSignal(code, detail)], codes from
                              similarity_signal (ask Miusan for new codes)
        similarity_score      optional, 0..1, internal only

    Missing values must never count as a match (AC2): two reports that both
    lack a depth do not have "similar depth".
    """

    raise NotImplementedError(
        "Related Incident Detection matching is not implemented yet"
    )


async def run_related_incident_detection(
    db: AsyncSession,
    report_reference: str,
) -> DetectionRunState | None:
    """
    Analyse one report and store the outcome. Never raises.

    Returns the final run state, FAILED when anything went wrong, or None
    when the report is not eligible (withdrawn, not yet at intake).

    The run is committed as 'processing' before matching starts, so a
    Coordinator who opens the report meanwhile sees "analysis in progress"
    rather than nothing.
    """

    the_run_id: int | None = None

    try:
        the_source_row = await the_repository.get_report_comparison_facts(
            db=db,
            report_reference=report_reference,
        )

        if the_source_row is None:
            return None

        the_source = ReportComparisonFacts(**the_source_row)

        the_run_id = await the_repository.begin_detection_run(
            db=db,
            report_id=the_source.report_id,
            rule_version=RULE_VERSION,
        )

        await db.commit()

        the_pool_rows = await the_repository.list_candidate_comparison_facts(
            db=db,
            source_report_id=the_source.report_id,
            observed_from=the_source.observed_at - CANDIDATE_WINDOW,
            observed_to=the_source.observed_at + CANDIDATE_WINDOW,
            limit=CANDIDATE_POOL_LIMIT,
        )

        the_pool = [ReportComparisonFacts(**the_row) for the_row in the_pool_rows]

        the_outcome = await match_related_reports(the_source, the_pool)

        if the_outcome.run_state not in (
            DetectionRunState.COMPLETED,
            DetectionRunState.INSUFFICIENT_INFORMATION,
        ):
            raise ValueError(
                f"The engine returned an invalid run state: {the_outcome.run_state}"
            )

        if the_outcome.run_state == DetectionRunState.COMPLETED:
            await the_repository.save_detection_candidates(
                db=db,
                run_id=the_run_id,
                report_id=the_source.report_id,
                candidates=the_outcome.candidates,
            )

        await the_repository.finish_detection_run(
            db=db,
            run_id=the_run_id,
            run_state=the_outcome.run_state,
        )

        await db.commit()

        return the_outcome.run_state

    except Exception:
        # report reference only: never log report content or locations
        logger.exception(
            "Related Incident Detection failed for %s",
            report_reference,
        )

        await db.rollback()

        if the_run_id is not None:
            try:
                await the_repository.finish_detection_run(
                    db=db,
                    run_id=the_run_id,
                    run_state=DetectionRunState.FAILED,
                )
                await db.commit()

            except Exception:
                logger.exception(
                    "Could not mark the detection run failed for %s",
                    report_reference,
                )
                await db.rollback()

        return DetectionRunState.FAILED


async def run_related_incident_detection_in_background(
    report_reference: str,
) -> None:
    """
    Background-task entry point with its own session. Never raises.
    """

    try:
        async with AsyncSessionLocal() as the_session:
            await run_related_incident_detection(
                db=the_session,
                report_reference=report_reference,
            )

    except Exception:
        logger.exception(
            "Related Incident Detection could not start for %s",
            report_reference,
        )
