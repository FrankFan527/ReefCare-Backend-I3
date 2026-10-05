"""US5.9 data-assisted matching. Produces suggestions; never makes case decisions.

All persistence goes through related_incident_repository. Description vectors
stay in memory; signal details contain only fixed, public-safe explanations.
"""

import asyncio
import logging
import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import asin, cos, log, radians, sin, sqrt

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.repositories import related_incident_repository as the_repository, image_embedding_repository
from app.services import image_embedding_service as image_service
from app.schemas.related_incident import (
    CandidateMatch, CandidateSignal, DetectionOutcome, DetectionRunState,
    RelatednessLevel, ReportComparisonFacts,
    ImageAnalysisState,
)

logger = logging.getLogger(__name__)
RULE_VERSION = settings.related_incident_rule_version
CANDIDATE_WINDOW = timedelta(days=settings.related_incident_window_days)
CANDIDATE_POOL_LIMIT = settings.related_incident_pool_limit

# Missing and unknown values must not become equal comparison values.
MISSING_LABELS = {"", "unknown", "unsure", "not specified", "not_specified", "not included", "not_included", "n/a", "none"}
COORDINATE_SOURCES = {"manual_map_pin", "entered_coordinates", "device_metadata"}
CONFIDENCE_UNCERTAINTY = {"exact": 0, "within_100m": 100, "within_1km": 1000}
STOP_WORDS = set("""
    a an the and or but of on in at to for with from near around was were is
    are be been i we my our it its this that there here saw see observed
    observation report reported dive diving site metre metres meter meters
    dan di ke dari yang ini itu saya kami ada dengan pada sekitar terlihat
""".split())
MAX_DESCRIPTION_CHARS = 4000


@dataclass(frozen=True)
class MatchingRules:
    """Draft thresholds requiring calibration against reviewed ReefCare pairs."""

    window_days: int = settings.related_incident_window_days
    nearby_metres: float = settings.related_incident_nearby_metres
    depth_tolerance_metres: float = settings.related_incident_depth_tolerance_metres
    description_threshold: float = settings.related_incident_description_threshold
    minimum_score: float = settings.related_incident_min_score
    medium_score: float = settings.related_incident_medium_score
    high_score: float = settings.related_incident_high_score
    result_limit: int = settings.related_incident_result_limit
    image_threshold: float = settings.related_incident_image_threshold
    image_top_k: int = settings.related_incident_image_top_k
    images_enabled: bool = settings.related_incident_images_enabled


def _label(value: str | None) -> str | None:
    normalised = " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())
    return normalised if normalised not in MISSING_LABELS else None


def _utc(value: datetime) -> datetime:
    # PostgreSQL timestamptz values are aware. Treat legacy naive values as UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _point(facts: ReportComparisonFacts) -> tuple[float, float] | None:
    if (facts.location_source_code not in COORDINATE_SOURCES
            or facts.location_confidence_code not in CONFIDENCE_UNCERTAINTY
            or facts.generalised_latitude is None or facts.generalised_longitude is None):
        return None
    lat, lon = float(facts.generalised_latitude), float(facts.generalised_longitude)
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def _distance_metres(first: tuple[float, float], second: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*first, *second))
    haversine = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * asin(sqrt(min(1.0, max(0.0, haversine))))


def _has_spatial_context(facts: ReportComparisonFacts) -> bool:
    return facts.dive_site_id is not None or _label(facts.public_area_label) is not None or _point(facts) is not None


def _tokens(value: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)


def _description_terms(facts: ReportComparisonFacts) -> Counter:
    # Site/area names already contribute spatial evidence: remove them from
    # description similarity to avoid counting the same fact twice.
    location_words = set(_tokens(facts.dive_site_name)) | set(_tokens(facts.public_area_label))
    terms = Counter(word for word in _tokens((facts.description or "")[:MAX_DESCRIPTION_CHARS])
                    if len(word) > 2 and word not in STOP_WORDS and word not in location_words)
    return terms if len(terms) >= 3 else Counter()


def _description_similarities(source: ReportComparisonFacts, pool: list[ReportComparisonFacts]) -> list[float]:
    """Local TF-IDF cosine similarity, with no external service or text storage."""
    documents = [_description_terms(facts) for facts in [source, *pool]]
    frequencies = Counter(term for document in documents for term in document)
    idf = {term: 1 + log((len(documents) + 1) / (frequency + 1))
           for term, frequency in frequencies.items()}
    vectors = [{term: (1 + log(count)) * idf[term] for term, count in document.items()}
               for document in documents]
    norms = [sqrt(sum(weight * weight for weight in vector.values())) for vector in vectors]
    similarities = []
    for index, vector in enumerate(vectors[1:], start=1):
        denominator = norms[0] * norms[index]
        similarity = (sum(weight * vector.get(term, 0) for term, weight in vectors[0].items()) / denominator
                      if denominator else 0.0)
        similarities.append(min(1.0, max(0.0, similarity)))
    return similarities


def _signal(code: str, score: float, weight: float, detail: str | None = None) -> CandidateSignal:
    return CandidateSignal(code, detail, Decimal(str(round(score, 4))), Decimal(str(weight)))


def _spatial_match(source: ReportComparisonFacts, candidate: ReportComparisonFacts, rules: MatchingRules):
    signals = []
    same_site = source.dive_site_id is not None and source.dive_site_id == candidate.dive_site_id
    area = _label(source.public_area_label)
    same_area = area is not None and area == _label(candidate.public_area_label)
    source_point, candidate_point = _point(source), _point(candidate)
    nearby = precise_enough = False
    if source_point is not None and candidate_point is not None:
        distance = _distance_metres(source_point, candidate_point)
        uncertainty = (CONFIDENCE_UNCERTAINTY[source.location_confidence_code]
                       + CONFIDENCE_UNCERTAINTY[candidate.location_confidence_code])
        if distance > rules.nearby_metres + uncertainty + 160:
            return None
        nearby = distance <= rules.nearby_metres
        precise_enough = uncertainty <= 200
    strong = same_site or (nearby and precise_enough)
    if not (same_site or same_area or nearby):
        return None
    primary = "same_dive_site" if same_site else "nearby_location" if nearby and precise_enough else "same_general_area" if same_area else "nearby_location"
    signals.append(_signal(primary, 1.0 if strong else 0.5, 0.30,
                           "Generalised locations; observer uncertainty applies." if primary == "nearby_location" else None))
    # Supporting spatial explanations do not receive another spatial weight.
    if nearby and primary != "nearby_location":
        signals.append(_signal("nearby_location", 1.0, 0.0, "Nearby generalised locations; observer uncertainty applies."))
    if same_area and not same_site and primary != "same_general_area":
        signals.append(_signal("same_general_area", 1.0, 0.0))
    return signals, strong


def _eligible_pool(source: ReportComparisonFacts, pool: list[ReportComparisonFacts], rules: MatchingRules):
    if source.observed_at is None:
        return []
    return [report for report in pool if report.report_id != source.report_id
            and report.observed_at is not None
            and _label(report.threat_category_code) == _label(source.threat_category_code)
            and abs((_utc(source.observed_at)-_utc(report.observed_at)).total_seconds()) <= rules.window_days*86400
            and _spatial_match(source, report, rules) is not None]


async def match_related_reports(
    the_source: ReportComparisonFacts,
    the_pool: list[ReportComparisonFacts],
    rules: MatchingRules | None = None,
) -> DetectionOutcome:
    # Pure CPU comparison stays outside the event loop. Cancellation abandons
    # its result; this thread never touches the DB or makes a human decision.
    return await asyncio.to_thread(_match_related_reports, the_source, the_pool, rules)


def _match_related_reports(
    the_source: ReportComparisonFacts,
    the_pool: list[ReportComparisonFacts],
    rules: MatchingRules | None = None,
) -> DetectionOutcome:
    """TF-IDF text + exact image KNN + mandatory structured corroboration.

    Fixed weights: spatial .30, time .15, threat .15, text .20, depth .05,
    image .15. Missing channels contribute zero; never renormalise upwards.
    A shared general area requires text or image support and cannot yield High.
    This score is a retrieval heuristic, never a probability or human decision.
    """
    rules = rules or MatchingRules()
    if (the_source.observed_at is None or _label(the_source.threat_category_code) is None
            or not _has_spatial_context(the_source)):
        return DetectionOutcome(DetectionRunState.INSUFFICIENT_INFORMATION)
    pool = _eligible_pool(the_source, the_pool, rules)
    similarities = _description_similarities(the_source, pool)
    image_scores = image_service.nearest_image_reports(the_source, pool, rules.image_top_k) if rules.images_enabled else {}
    matches: dict[int, CandidateMatch] = {}
    
    for candidate, text_similarity in zip(pool, similarities):
        signals, strong_spatial = _spatial_match(the_source, candidate, rules)
        image_similarity = image_scores.get(candidate.report_id, 0.0)
        description_matches = text_similarity >= rules.description_threshold
        image_matches = rules.images_enabled and image_similarity >= rules.image_threshold
        
        if not strong_spatial and not (description_matches or image_matches):
            continue

        elapsed_hours = abs((_utc(the_source.observed_at)-_utc(candidate.observed_at)).total_seconds())/3600
        signals.append(_signal("close_observation_time", 1.0 if elapsed_hours <= 48 else 0.5, 0.15,
                               "Observation dates within 2 days." if elapsed_hours <= 48 else f"Observation dates within {rules.window_days} days."))
        signals.append(_signal("same_threat_category", 1.0, 0.15))
        
        if description_matches:
            signals.append(_signal("similar_description", text_similarity, 0.20,
                                   "Descriptions share relevant terms; text similarity is not verification."))
        
        if image_matches:
            signals.append(_signal("similar_image", image_similarity, 0.15,
                                   "Photos have similar visual features; this does not verify the same incident."))
        
        if the_source.estimated_depth_metres is not None and candidate.estimated_depth_metres is not None:
            first, second = float(the_source.estimated_depth_metres), float(candidate.estimated_depth_metres)
            if first >= 0 and second >= 0 and abs(first-second) <= rules.depth_tolerance_metres:
                signals.append(_signal("similar_depth", 1.0, 0.05,
                                       f"Estimated depths within {rules.depth_tolerance_metres:g} metres."))
        
        score = sum(float(signal.signal_score)*float(signal.signal_weight) for signal in signals)
        if not strong_spatial:
            score = min(score, rules.high_score-0.01)
        
        if score + 1e-9 < rules.minimum_score:
            continue
        
        level = (RelatednessLevel.HIGH if score+1e-9 >= rules.high_score else
                 RelatednessLevel.MEDIUM if score+1e-9 >= rules.medium_score else RelatednessLevel.LOW)
        
        match = CandidateMatch(candidate.report_id, level, signals, Decimal(str(round(min(score, 1.0), 4))))
        
        previous = matches.get(candidate.report_id)
        
        if previous is None or match.similarity_score > previous.similarity_score:
            matches[candidate.report_id] = match
    
    ranked = sorted(matches.values(), key=lambda match: (-match.similarity_score, match.candidate_report_id))
    
    return DetectionOutcome(DetectionRunState.COMPLETED, ranked[:rules.result_limit])


def _input_fingerprint(source, pool, image_rows, rules):
    # Only the digest is persisted. Ownership is absent: it is filtered when read.
    payload = {"source": asdict(source), "pool": [asdict(report) for report in pool],
               "images": [{key: row.get(key) for key in ("evidence_id", "report_id", "uploaded_at",
                           "image_embedding_model", "image_embedding_version", "image_embedding_generated_at")}
                          for row in image_rows], "rules": asdict(rules)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


async def _rollback_safely(db: AsyncSession) -> None:
    try:
        await asyncio.wait_for(db.rollback(), timeout=5)
    except Exception as error:
        logger.warning("Related-incident rollback failed (%s)", type(error).__name__)


async def run_related_incident_detection(
    db: AsyncSession,
    report_reference: str,
    *,
    generate_embeddings: bool = False,
    force: bool = False,
) -> DetectionRunState | None:
    """Run bounded related-incident detection for one committed report.

    Report submission schedules this after its commit. When requested,
    missing image embeddings for the newly submitted report are generated
    before matching.

    Image-generation failure does not prevent the remaining US5.9 signals
    from being evaluated. Database/matching failures mark the run failed.
    """
    run_id: int | None = None

    try:
        async with asyncio.timeout(
            settings.related_incident_timeout_seconds
        ):
            source_row = (
                await the_repository.get_report_comparison_facts(
                    db=db,
                    report_reference=report_reference,
                )
            )

            if source_row is None:
                return None

            source = ReportComparisonFacts(**source_row)
            rules = MatchingRules()

            pool_rows = []

            if source.observed_at is not None:
                pool_rows = (
                    await the_repository.list_candidate_comparison_facts(
                        db=db,
                        source_report_id=source.report_id,
                        observed_from=(
                            source.observed_at - CANDIDATE_WINDOW
                        ),
                        observed_to=(
                            source.observed_at + CANDIDATE_WINDOW
                        ),
                        limit=CANDIDATE_POOL_LIMIT,
                    )
                )

            pool = _eligible_pool(
                source,
                [
                    ReportComparisonFacts(**row)
                    for row in pool_rows
                ],
                rules,
            )

            image_rows = []
            image_state = ImageAnalysisState.DISABLED

            if rules.images_enabled:
                ids = [
                    source.report_id,
                    *[
                        report.report_id
                        for report in pool
                    ],
                ]

                image_rows = (
                    await image_embedding_repository.list_image_inputs(
                        db,
                        ids,
                        settings.related_incident_images_per_report,
                    )
                )

                if generate_embeddings:
                    # Only generate embeddings for the newly submitted
                    # source report. Candidate reports should already have
                    # cached embeddings from their own submission.
                    source_images = [
                        row
                        for row in image_rows
                        if row["report_id"] == source.report_id
                    ]

                    if source_images:
                        try:
                            async with asyncio.timeout(
                                settings.related_incident_timeout_seconds
                                / 2
                            ):
                                await (
                                    image_service
                                    .generate_missing_embeddings(
                                        db,
                                        source_images,
                                    )
                                )

                            # Persist embeddings independently from the
                            # later detection transaction.
                            await db.commit()

                        except TimeoutError:
                            logger.warning(
                                "Image generation budget exhausted "
                                "for %s",
                                report_reference,
                            )

                            # Cancellation may have interrupted DB work.
                            await _rollback_safely(db)

                        # Reload from DB so matching only uses
                        # successfully persisted embeddings.
                        image_rows = (
                            await image_embedding_repository
                            .list_image_inputs(
                                db,
                                ids,
                                settings
                                .related_incident_images_per_report,
                            )
                        )

                source, pool, image_state = (
                    image_service.attach_embeddings(
                        source,
                        pool,
                        image_rows,
                    )
                )

            fingerprint = _input_fingerprint(
                source,
                pool,
                image_rows,
                rules,
            )

            latest = (
                await the_repository.get_latest_detection_run(
                    db=db,
                    report_id=source.report_id,
                )
            )

            if (
                not force
                and latest
                and latest.get("rule_version") == RULE_VERSION
                and latest.get("input_fingerprint") == fingerprint
                and latest["run_state"]
                in (
                    "completed",
                    "insufficient_information",
                )
            ):
                return DetectionRunState(
                    latest["run_state"]
                )

            run_id = await the_repository.begin_detection_run(
                db=db,
                report_id=source.report_id,
                rule_version=RULE_VERSION,
                input_fingerprint=fingerprint,
            )

            if run_id is None:
                await _rollback_safely(db)
                return DetectionRunState.PROCESSING

            await db.commit()

            outcome = await match_related_reports(
                source,
                pool,
                rules,
            )

            if outcome.run_state not in (
                DetectionRunState.COMPLETED,
                DetectionRunState.INSUFFICIENT_INFORMATION,
            ):
                raise ValueError(
                    "Invalid detection outcome"
                )

            if (
                outcome.run_state
                == DetectionRunState.COMPLETED
            ):
                await (
                    the_repository.save_detection_candidates(
                        db=db,
                        run_id=run_id,
                        report_id=source.report_id,
                        candidates=outcome.candidates,
                    )
                )

            await the_repository.finish_detection_run(
                db=db,
                run_id=run_id,
                run_state=outcome.run_state,
                image_analysis_state=image_state,
            )

            await db.commit()

            return outcome.run_state

    except Exception as error:
        logger.warning(
            "Related-incident detection failed for %s (%s)",
            report_reference,
            type(error).__name__,
        )

        await _rollback_safely(db)

        if run_id is not None:
            try:
                async with asyncio.timeout(5):
                    await the_repository.finish_detection_run(
                        db=db,
                        run_id=run_id,
                        run_state=DetectionRunState.FAILED,
                        image_analysis_state=(
                            ImageAnalysisState.UNAVAILABLE
                        ),
                    )

                    await db.commit()

            except Exception as cleanup_error:
                logger.warning(
                    "Related-incident failure could not "
                    "be recorded (%s)",
                    type(cleanup_error).__name__,
                )

                await _rollback_safely(db)

        return DetectionRunState.FAILED


async def run_related_incident_detection_in_background(
    report_reference: str,
) -> None:
    """
    Submission-triggered US5.9 processing.

    Generate missing embeddings for this newly
    submitted report, then perform matching.
    """

    try:

        async with AsyncSessionLocal() as session:

            await run_related_incident_detection(
                db=session,
                report_reference=report_reference,
                generate_embeddings=True,
            )

    except Exception as error:

        logger.warning(
            "Related-incident background "
            "task failed for %s (%s)",
            report_reference,
            type(error).__name__,
        )