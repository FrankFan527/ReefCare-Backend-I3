# ---------------------------------------------------------------------------
# US5.9 Related Incidents — Coordinator workflow (normal E5, Miusan).
#
# Services decide; repositories carry out. The detection engine is NOT called
# from here: this service only reads what the engine already stored (AC3:
# "display the results already produced").
#
# Every entry point starts with load_owned_case() on the current report, so a
# Coordinator who does not own it learns nothing about its candidates.
#
# PostgreSQL is still the final authority on decisions. The Python ownership
# checks below exist to return clear 403/404s early; the decision functions
# re-check ownership inside the database (RC403) regardless.
# ---------------------------------------------------------------------------

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    DatabaseOperationError,
    DomainValidationError,
    NotFoundError,
    WorkflowError,
)
from app.repositories import related_incident_repository as the_repository
from app.schemas.related_incident import (
    CandidateDecisionState,
    CandidateOwnershipState,
    ComparisonEvidenceItem,
    ComparisonReportSide,
    DetectionRunState,
    ImageAnalysisState,
    LatestRelationshipDecision,
    RejectionReasonOption,
    RelatedAnalysisState,
    RelatedReportCandidate,
    RelatedReportSignal,
    RelatedReportsResponse,
    RelationshipDecision,
    RelationshipDecisionCreate,
    RelationshipDecisionResponse,
    ReportComparisonResponse,
)
from app.services.case_ownership_service import (
    claim_report as claim_report_service,
)
from app.services.case_workflow_service import load_owned_case


logger = logging.getLogger(__name__)

IMAGE_ANALYSIS_MESSAGES = {
    ImageAnalysisState.NOT_ANALYSED: "Image analysis has not completed.",
    ImageAnalysisState.DISABLED: "Image comparison is disabled.",
    ImageAnalysisState.NO_SOURCE_IMAGES: "This report has no eligible photos to compare.",
    ImageAnalysisState.UNAVAILABLE: "Image comparison is unavailable. Review the available report details.",
    ImageAnalysisState.INSUFFICIENT_HISTORY: "No compatible historical photo features were available in the comparison pool.",
    ImageAnalysisState.PARTIAL: "Some photos could not be compared; available photos and report details were used.",
    ImageAnalysisState.READY: "Eligible cached photo features were compared within the report pool.",
}


# a run still "processing" after this long is treated as dead; on Vercel a
# background task can be cut off after the response, and AC9 says that must
# read as "analysis unavailable", never as "in progress" forever
STALE_PROCESSING_AFTER: timedelta = timedelta(minutes=5)


# plain-language lines for each analysis state; the UI can show them as-is
THE_ANALYSIS_MESSAGES: dict[RelatedAnalysisState, str] = {
    RelatedAnalysisState.PROCESSING:
        "Related-report analysis is in progress.",
    RelatedAnalysisState.MATCHES_AVAILABLE:
        "Potentially related reports are available for review.",
    RelatedAnalysisState.INSUFFICIENT_INFORMATION:
        "This report does not contain enough information to compare with other reports.",
    RelatedAnalysisState.NO_AVAILABLE_MATCHES:
        "No related reports are available to you.",
    RelatedAnalysisState.UNAVAILABLE:
        "Related-report analysis is unavailable. You can continue reviewing this report as normal.",
}


# PostgreSQL function errors -> the shared ServiceError mapping
THE_SQLSTATE_TO_SERVICE_ERROR: dict[str, type] = {
    "RC400": DomainValidationError,
    "RC403": AuthorizationError,
    "RC404": NotFoundError,
    "RC409": WorkflowError,
}


# ---------------------------------------------------------------------------
# Small pure helpers (unit-tested without a database)
# ---------------------------------------------------------------------------

def derive_analysis_state(
    the_run: dict | None,
    the_actionable_candidate_count: int,
    the_now: datetime,
) -> RelatedAnalysisState:
    """
    Translate the stored run into what the Coordinator is told (AC3, AC9).

    Never analysed, failed and stale-processing all become UNAVAILABLE.
    A completed run whose candidates were all filtered out by AC4 becomes
    NO_AVAILABLE_MATCHES, which is worded "available to you" on purpose.
    """

    if the_run is None:
        return RelatedAnalysisState.UNAVAILABLE

    the_state = the_run["run_state"]

    if the_state == DetectionRunState.PROCESSING.value:
        if the_now - the_run["started_at"] > STALE_PROCESSING_AFTER:
            return RelatedAnalysisState.UNAVAILABLE
        return RelatedAnalysisState.PROCESSING

    if the_state == DetectionRunState.FAILED.value:
        return RelatedAnalysisState.UNAVAILABLE

    if the_state == DetectionRunState.INSUFFICIENT_INFORMATION.value:
        return RelatedAnalysisState.INSUFFICIENT_INFORMATION

    if the_state == DetectionRunState.COMPLETED.value:
        if the_actionable_candidate_count > 0:
            return RelatedAnalysisState.MATCHES_AVAILABLE
        return RelatedAnalysisState.NO_AVAILABLE_MATCHES

    # an unknown stored state is a bug, but it must not block review
    return RelatedAnalysisState.UNAVAILABLE


def derive_ownership_state(
    the_candidate_owner_id: int | None,
    the_coordinator_id: int,
) -> CandidateOwnershipState | None:
    """
    AC4. None means "owned by another Coordinator": filter it out.
    """

    if the_candidate_owner_id is None:
        return CandidateOwnershipState.UNCLAIMED

    if the_candidate_owner_id == the_coordinator_id:
        return CandidateOwnershipState.OWNED_BY_YOU

    return None


def derive_decision_state(
    the_current_incident_id: int | None,
    the_candidate_incident_id: int | None,
    the_latest_decision: dict | None,
    the_latest_evidence_at: datetime | None,
) -> tuple[CandidateDecisionState, bool]:
    """
    The decision state of one pair, plus whether a Not Related pair has been
    reopened by new evidence (AC7).

    Sharing an incident always reads as LINKED, even without a decision row
    on this exact pair (A-B and B-C confirmed means A and C share it too).
    """

    if (
        the_current_incident_id is not None
        and the_current_incident_id == the_candidate_incident_id
    ):
        return CandidateDecisionState.LINKED, False

    if the_latest_decision is None:
        return CandidateDecisionState.UNDECIDED, False

    if the_latest_decision["decision"] == RelationshipDecision.NOT_RELATED.value:
        the_new_evidence_since = (
            the_latest_evidence_at is not None
            and the_latest_evidence_at > the_latest_decision["decided_at"]
        )

        if the_new_evidence_since:
            return CandidateDecisionState.UNDECIDED, True

        return CandidateDecisionState.NOT_RELATED, False

    # a same_incident decision whose link no longer holds should not happen
    # (unlinking is outside I3); show it as undecided rather than claim a link
    return CandidateDecisionState.UNDECIDED, False


def raise_mapped_database_error(
    the_error: DBAPIError,
) -> NoReturn:
    """
    Map an RC4xx raised by the decision functions to the shared error
    contract. Anything else becomes a generic 500 with no database detail.
    """

    the_sqlstate = getattr(the_error.orig, "sqlstate", None)
    the_error_class = THE_SQLSTATE_TO_SERVICE_ERROR.get(the_sqlstate)

    if the_error_class is None:
        raise DatabaseOperationError(
            "The relationship decision could not be recorded"
        ) from the_error

    # messages are written by us in the migration, so they are safe to return
    the_diagnostics = getattr(the_error.orig, "diag", None)
    the_message = getattr(the_diagnostics, "message_primary", None)

    raise the_error_class(the_message) from the_error


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# AC3 / AC4 / AC7 / AC9 — Potentially Related Reports
# ---------------------------------------------------------------------------

async def get_related_reports(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> RelatedReportsResponse:
    """
    Potentially Related Reports for a report the Coordinator has claimed.

    Ownership errors propagate (403/404). Anything that goes wrong while
    reading the analysis is logged and returned as UNAVAILABLE, because AC9
    requires normal review to continue when related-report analysis fails.
    """

    await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    try:
        async with asyncio.timeout(settings.related_incident_timeout_seconds):
            return await _build_related_reports(
                db=db,
                report_reference=report_reference,
                coordinator_id=coordinator_id,
            )

    except (SQLAlchemyError, ValueError, KeyError, TypeError, TimeoutError) as error:
        # Corrupt analysis rows also degrade gracefully. Avoid SQL parameters
        # in logs, and clear a failed transaction before this session is reused.
        logger.warning("Related-report analysis could not be read for %s (%s)",
                       report_reference, type(error).__name__)
        try:
            await asyncio.wait_for(db.rollback(), timeout=5)
        except Exception:
            logger.warning("Related-report analysis rollback failed")

        return RelatedReportsResponse(
            report_reference=report_reference,
            analysis_state=RelatedAnalysisState.UNAVAILABLE,
            message=THE_ANALYSIS_MESSAGES[RelatedAnalysisState.UNAVAILABLE],
        )


async def _build_related_reports(
    db: AsyncSession,
    report_reference: str,
    coordinator_id: int,
) -> RelatedReportsResponse:
    the_current = await the_repository.get_report_identity(
        db=db,
        report_reference=report_reference,
    )

    if the_current is None:
        raise NotFoundError(f"Report {report_reference} not found")

    the_run = await the_repository.get_latest_detection_run(
        db=db,
        report_id=the_current["report_id"],
    )

    the_candidates: list[RelatedReportCandidate] = []

    if (
        the_run is not None
        and the_run["run_state"] == DetectionRunState.COMPLETED.value
    ):
        the_candidates = await _build_actionable_candidates(
            db=db,
            the_current=the_current,
            the_run=the_run,
            coordinator_id=coordinator_id,
        )

    the_state = derive_analysis_state(
        the_run=the_run,
        the_actionable_candidate_count=len(the_candidates),
        the_now=utc_now(),
    )
    image_state = ImageAnalysisState(the_run.get("image_analysis_state", "not_analysed")) if the_run else ImageAnalysisState.NOT_ANALYSED

    return RelatedReportsResponse(
        report_reference=report_reference,
        analysis_state=the_state,
        message=THE_ANALYSIS_MESSAGES[the_state],
        rule_version=the_run["rule_version"] if the_run else None,
        input_version=the_run.get("input_version") if the_run else None,
        image_analysis_state=image_state,
        image_analysis_message=IMAGE_ANALYSIS_MESSAGES[image_state],
        analysed_at=the_run["finished_at"] if the_run else None,
        candidates=the_candidates,
    )


async def _build_actionable_candidates(
    db: AsyncSession,
    the_current: dict,
    the_run: dict,
    coordinator_id: int,
) -> list[RelatedReportCandidate]:
    """
    Apply AC4 (unclaimed or owned by you only), attach signals, and work out
    the decision state of every remaining pair.
    """

    the_run_id = the_run["related_incident_run_id"]

    the_rows = await the_repository.list_run_candidates(db=db, run_id=the_run_id)

    the_visible_rows: list[tuple[dict, CandidateOwnershipState]] = []

    for the_row in the_rows:
        the_ownership = derive_ownership_state(
            the_candidate_owner_id=the_row["candidate_claimed_by_user_id"],
            the_coordinator_id=coordinator_id,
        )

        # owned by another Coordinator: outside the I3 workflow (AC4)
        if the_ownership is not None:
            the_visible_rows.append((the_row, the_ownership))

    if not the_visible_rows:
        return []

    the_signal_rows = await the_repository.list_run_candidate_signals(
        db=db,
        run_id=the_run_id,
    )

    the_signals_by_candidate: dict[int, list[RelatedReportSignal]] = {}

    for the_signal in the_signal_rows:
        the_signals_by_candidate.setdefault(
            the_signal["related_incident_candidate_id"], []
        ).append(
            RelatedReportSignal(
                code=the_signal["code"],
                label=the_signal["label"],
                detail=the_signal["detail"],
                signal_score=the_signal.get("signal_score"),
                signal_weight=the_signal.get("signal_weight"),
            )
        )

    the_other_ids = [the_row["candidate_report_id"] for the_row, _ in the_visible_rows]

    the_decisions = await the_repository.list_latest_pair_decisions(
        db=db,
        report_id=the_current["report_id"],
        other_report_ids=the_other_ids,
    )

    the_decision_by_other = {d["other_report_id"]: d for d in the_decisions}

    the_evidence_times = await the_repository.get_latest_evidence_times(
        db=db,
        report_ids=[the_current["report_id"], *the_other_ids],
    )

    the_current_evidence_at = the_evidence_times.get(the_current["report_id"])

    the_candidates: list[RelatedReportCandidate] = []

    for the_row, the_ownership in the_visible_rows:
        the_candidate_id = the_row["candidate_report_id"]

        # new evidence on EITHER report can justify reconsideration (AC7)
        the_pair_latest_evidence = max(
            (
                t for t in (
                    the_current_evidence_at,
                    the_evidence_times.get(the_candidate_id),
                )
                if t is not None
            ),
            default=None,
        )

        the_decision_state, the_reopened = derive_decision_state(
            the_current_incident_id=the_current["incident_id"],
            the_candidate_incident_id=the_row["candidate_incident_id"],
            the_latest_decision=the_decision_by_other.get(the_candidate_id),
            the_latest_evidence_at=the_pair_latest_evidence,
        )

        the_candidates.append(
            RelatedReportCandidate(
                candidate_report_reference=the_row["candidate_report_reference"],
                relatedness_level=the_row["relatedness_level"],
                relatedness_score=the_row.get("similarity_score"),
                signals=the_signals_by_candidate.get(
                    the_row["related_incident_candidate_id"], []
                ),
                ownership_state=the_ownership,
                decision_state=the_decision_state,
                reopened_by_new_evidence=the_reopened,
            )
        )

    return the_candidates


# ---------------------------------------------------------------------------
# AC5 — Claim and Compare
# ---------------------------------------------------------------------------

async def claim_and_compare(
    db: AsyncSession,
    report_reference: str,
    candidate_reference: str,
    coordinator_id: int,
) -> ReportComparisonResponse:
    """
    Claim an unclaimed candidate, then open the same-owner comparison.

    The claim itself is reefcare_claim_report() through the existing I2
    ownership service, so the race is decided by PostgreSQL. Losing the race
    returns 409 and the candidate drops out of this Coordinator's list.

    Only a candidate that the latest analysis actually suggested can be
    claimed from here; the normal queue remains the route for anything else.
    """

    await load_owned_case(
        db=db,
        report_reference=report_reference,
        coordinator_id=coordinator_id,
    )

    the_current = await the_repository.get_report_identity(db=db, report_reference=report_reference)
    the_candidate = await the_repository.get_report_identity(db=db, report_reference=candidate_reference)

    if the_current is None or the_candidate is None:
        raise NotFoundError("Report not found")

    the_suggestion = await the_repository.find_candidate_in_latest_run(
        db=db,
        report_id=the_current["report_id"],
        candidate_report_id=the_candidate["report_id"],
    )

    if the_suggestion is None:
        raise NotFoundError(
            f"Report {candidate_reference} is not a potential match for {report_reference}"
        )

    the_owner = the_candidate["claimed_by_user_id"]

    if the_owner is not None and the_owner != coordinator_id:
        raise ConflictError(
            "This report has been claimed by another Coordinator and is no longer available for comparison"
        )

    if the_owner is None:
        try:
            await claim_report_service(
                db=db,
                report_reference=candidate_reference,
                coordinator_id=coordinator_id,
            )

        except ConflictError as the_lost_race:
            raise ConflictError(
                "Another Coordinator claimed this report first, so it is no longer available for comparison"
            ) from the_lost_race

    return await compare_reports(
        db=db,
        report_reference=report_reference,
        candidate_reference=candidate_reference,
        coordinator_id=coordinator_id,
    )


# ---------------------------------------------------------------------------
# AC6 — side-by-side comparison
# ---------------------------------------------------------------------------

async def compare_reports(
    db: AsyncSession,
    report_reference: str,
    candidate_reference: str,
    coordinator_id: int,
) -> ReportComparisonResponse:
    """
    Both reports must be owned by the acting Coordinator before any
    protected detail is read (US1.3 AC2: relatedness never bypasses claim).
    """

    if report_reference == candidate_reference:
        raise DomainValidationError("A report cannot be compared with itself")

    await load_owned_case(db=db, report_reference=report_reference, coordinator_id=coordinator_id)
    await load_owned_case(db=db, report_reference=candidate_reference, coordinator_id=coordinator_id)

    the_current_side = await the_repository.get_comparison_side(db=db, report_reference=report_reference, coordinator_id=coordinator_id)
    the_candidate_side = await the_repository.get_comparison_side(db=db, report_reference=candidate_reference, coordinator_id=coordinator_id)

    if the_current_side is None or the_candidate_side is None:
        raise NotFoundError("Report not found")

    the_suggestion = await _find_suggestion_either_direction(
        db=db,
        the_first_report_id=the_current_side["report_id"],
        the_second_report_id=the_candidate_side["report_id"],
    )

    the_decision = await the_repository.get_latest_pair_decision_detail(
        db=db,
        report_id=the_current_side["report_id"],
        other_report_id=the_candidate_side["report_id"],
    )

    return ReportComparisonResponse(
        current=_to_comparison_side(the_current_side),
        candidate=_to_comparison_side(the_candidate_side),
        signals=[
            RelatedReportSignal(**the_signal)
            for the_signal in (the_suggestion or {}).get("signals", [])
        ],
        relatedness_level=(the_suggestion or {}).get("relatedness_level"),
        relatedness_score=(the_suggestion or {}).get("similarity_score"),
        latest_decision=(
            LatestRelationshipDecision(**the_decision)
            if the_decision is not None
            else None
        ),
    )


def _to_comparison_side(
    the_side: dict,
) -> ComparisonReportSide:
    return ComparisonReportSide(
        report_reference=the_side["report_reference"],
        status_code=the_side["status_code"],
        status_label=the_side["status_label"],
        threat_category_code=the_side["threat_category_code"],
        threat_category_label=the_side["threat_category_label"],
        observed_at=the_side["observed_at"],
        submitted_at=the_side["submitted_at"],
        dive_site_name=the_side["dive_site_name"],
        public_area_label=the_side["public_area_label"],
        location_confidence_code=the_side["location_confidence_code"],
        estimated_depth_metres=the_side["estimated_depth_metres"],
        description=the_side["description"],
        incident_reference=the_side["incident_reference"],
        evidence=[
            ComparisonEvidenceItem(**the_item)
            for the_item in the_side["evidence"]
        ],
    )


async def _find_suggestion_either_direction(
    db: AsyncSession,
    the_first_report_id: int,
    the_second_report_id: int,
) -> dict | None:
    """
    The pair may have been suggested from either report's analysis, so look
    both ways. Used for signals in the compare view and as decision
    provenance (US1.4 AC4).
    """

    the_suggestion = await the_repository.find_candidate_in_latest_run(
        db=db,
        report_id=the_first_report_id,
        candidate_report_id=the_second_report_id,
    )

    if the_suggestion is not None:
        return the_suggestion

    return await the_repository.find_candidate_in_latest_run(
        db=db,
        report_id=the_second_report_id,
        candidate_report_id=the_first_report_id,
    )


# ---------------------------------------------------------------------------
# AC6 / AC7 — Confirm Same Incident / Not Related
# ---------------------------------------------------------------------------

async def record_relationship_decision(
    db: AsyncSession,
    report_reference: str,
    candidate_reference: str,
    coordinator_id: int,
    the_request: RelationshipDecisionCreate,
) -> RelationshipDecisionResponse:
    """
    Persist one human decision through the PostgreSQL functions.

    Nothing here changes case status, ownership, evidence or closure (AC8).
    The caller does not commit; this function commits on success and rolls
    back on any failure.
    """

    if report_reference == candidate_reference:
        raise DomainValidationError("A report cannot be related to itself")

    # early, readable 403/404s; PostgreSQL re-checks ownership regardless
    await load_owned_case(db=db, report_reference=report_reference, coordinator_id=coordinator_id)
    await load_owned_case(db=db, report_reference=candidate_reference, coordinator_id=coordinator_id)

    the_current = await the_repository.get_report_identity(db=db, report_reference=report_reference)
    the_candidate = await the_repository.get_report_identity(db=db, report_reference=candidate_reference)

    if the_current is None or the_candidate is None:
        raise NotFoundError("Report not found")

    the_suggestion = await _find_suggestion_either_direction(
        db=db,
        the_first_report_id=the_current["report_id"],
        the_second_report_id=the_candidate["report_id"],
    )

    the_rule_version = the_suggestion["rule_version"] if the_suggestion else None

    the_note = (the_request.note or "").strip() or None

    try:
        if the_request.decision == RelationshipDecision.SAME_INCIDENT:
            the_saved = await the_repository.confirm_same_incident(
                db=db,
                report_reference=report_reference,
                related_reference=candidate_reference,
                coordinator_id=coordinator_id,
                note=the_note,
                suggested_rule_version=the_rule_version,
            )

        else:
            the_saved = await the_repository.record_not_related(
                db=db,
                report_reference=report_reference,
                related_reference=candidate_reference,
                coordinator_id=coordinator_id,
                reason_code=the_request.rejection_reason_code.strip(),
                note=the_note,
                suggested_rule_version=the_rule_version,
            )

        await db.commit()

    except DBAPIError as the_error:
        await db.rollback()
        raise_mapped_database_error(the_error)

    except SQLAlchemyError as the_error:
        await db.rollback()
        raise DatabaseOperationError(
            "The relationship decision could not be recorded"
        ) from the_error

    return RelationshipDecisionResponse(
        report_reference=report_reference,
        related_report_reference=candidate_reference,
        decision=the_request.decision,
        incident_reference=the_saved.get("out_incident_reference"),
        rejection_reason_code=(
            the_request.rejection_reason_code.strip()
            if the_request.decision == RelationshipDecision.NOT_RELATED
            else None
        ),
        decided_by=coordinator_id,
        decided_at=the_saved["out_decided_at"],
    )


async def list_rejection_reason_options(
    db: AsyncSession,
) -> list[RejectionReasonOption]:
    the_rows = await the_repository.list_rejection_reasons(db=db)

    return [RejectionReasonOption(**the_row) for the_row in the_rows]
