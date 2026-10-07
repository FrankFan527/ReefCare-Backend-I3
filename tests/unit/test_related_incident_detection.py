from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.schemas.related_incident import DetectionOutcome, DetectionRunState, ReportComparisonFacts, RelatednessLevel
from app.services import related_incident_detection_service as engine

NOW = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
SOURCE = ReportComparisonFacts(
    report_id=1, report_reference="RC-0001", observed_at=NOW,
    threat_category_code="ghost_gear", dive_site_id=10,
    dive_site_name="Tiger Reef", public_area_label="Tioman",
    estimated_depth_metres=Decimal("15"),
    description="Large fishing net tangled around branching coral at Tiger Reef.",
)


def candidate(**changes):
    return replace(SOURCE, report_id=2, report_reference="RC-0002", **changes)


@pytest.mark.asyncio
async def test_same_issue_produces_explainable_high_suggestion():
    outcome = await engine.match_related_reports(SOURCE, [candidate(observed_at=NOW - timedelta(days=1))])
    assert outcome.run_state == DetectionRunState.COMPLETED
    match, = outcome.candidates
    assert match.relatedness_level == RelatednessLevel.HIGH
    assert {s.code for s in match.signals} >= {"same_dive_site", "same_threat_category", "close_observation_time", "similar_depth", "similar_description"}
    assert "fishing net" not in " ".join(s.detail or "" for s in match.signals)
    assert all(len(s.detail or "") <= 160 for s in match.signals)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"observed_at": None}, {"threat_category_code": None}, {"threat_category_code": "unsure"},
    {"dive_site_id": None, "public_area_label": None},
    {"dive_site_id": None, "public_area_label": "Unknown"},
])
async def test_missing_source_information_is_distinct_from_no_matches(changes):
    outcome = await engine.match_related_reports(replace(SOURCE, **changes), [candidate()])
    assert outcome.run_state == DetectionRunState.INSUFFICIENT_INFORMATION
    assert outcome.candidates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"threat_category_code": "marine_debris"}, {"threat_category_code": None},
    {"observed_at": None}, {"observed_at": NOW - timedelta(days=8)},
    {"dive_site_id": 11, "public_area_label": "Redang"},
    {"dive_site_id": None, "public_area_label": None},
])
async def test_unrelated_or_incomplete_candidates_are_not_suggested(changes):
    outcome = await engine.match_related_reports(SOURCE, [candidate(**changes)])
    assert outcome.run_state == DetectionRunState.COMPLETED
    assert outcome.candidates == []


@pytest.mark.asyncio
async def test_missing_values_do_not_inflate_relatedness():
    source = replace(SOURCE, description=None, estimated_depth_metres=None)
    outcome = await engine.match_related_reports(source, [replace(source, report_id=2)])
    match, = outcome.candidates
    assert match.relatedness_level == RelatednessLevel.LOW
    assert match.similarity_score == Decimal("0.6")
    assert {s.code for s in match.signals} == {"same_dive_site", "same_threat_category", "close_observation_time"}


@pytest.mark.asyncio
async def test_generic_area_requires_description_and_cannot_be_high():
    source = replace(SOURCE, dive_site_id=None)
    similar = replace(source, report_id=2)
    outcome = await engine.match_related_reports(source, [similar])
    assert outcome.candidates[0].relatedness_level != RelatednessLevel.HIGH
    unrelated = replace(similar, description="A small plastic bottle lying on sand.")
    assert (await engine.match_related_reports(source, [unrelated])).candidates == []


@pytest.mark.asyncio
async def test_site_names_and_empty_descriptions_are_not_description_matches():
    source = replace(SOURCE, description="Tiger Reef Tioman")
    outcome = await engine.match_related_reports(source, [replace(source, report_id=2)])
    assert "similar_description" not in {s.code for s in outcome.candidates[0].signals}


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,source_code", [(None,"manual_map_pin"), ("unsure","manual_map_pin"), ("exact","named_dive_site")])
async def test_uncertain_or_non_observation_coordinates_cannot_anchor_a_match(confidence, source_code):
    source = replace(SOURCE, dive_site_id=None, public_area_label=None,
                     generalised_latitude=Decimal("2.800"), generalised_longitude=Decimal("104.100"),
                     location_confidence_code=confidence, location_source_code=source_code)
    outcome = await engine.match_related_reports(source, [replace(source, report_id=2)])
    assert outcome.run_state == DetectionRunState.INSUFFICIENT_INFORMATION


@pytest.mark.asyncio
async def test_nearby_confident_generalised_coordinates_support_a_match():
    source = replace(SOURCE, dive_site_id=None, public_area_label=None,
                     generalised_latitude=Decimal("2.800"), generalised_longitude=Decimal("104.100"),
                     location_confidence_code="within_100m", location_source_code="manual_map_pin")
    match, = (await engine.match_related_reports(source, [replace(source, report_id=2, generalised_latitude=Decimal("2.801"))])).candidates
    assert match.relatedness_level == RelatednessLevel.HIGH
    assert "nearby_location" in {s.code for s in match.signals}
    assert "2.80" not in str(match.signals)


@pytest.mark.asyncio
async def test_contradictory_confident_pins_override_same_site_name():
    source = replace(SOURCE, generalised_latitude=Decimal("2.800"), generalised_longitude=Decimal("104.100"),
                     location_confidence_code="exact", location_source_code="manual_map_pin")
    other = replace(source, report_id=2, generalised_latitude=Decimal("3.800"))
    assert (await engine.match_related_reports(source, [other])).candidates == []


@pytest.mark.asyncio
async def test_uncertain_pins_do_not_override_same_site_name():
    source = replace(
        SOURCE,
        dive_site_id=15,
        generalised_latitude=Decimal("5.881"),
        generalised_longitude=Decimal("102.712"),
        location_confidence_code="within_1km",
        location_source_code="manual_map_pin",
    )

    other = replace(
        source,
        report_id=2,
        generalised_latitude=Decimal("5.904"),
        generalised_longitude=Decimal("102.693"),
    )

    outcome = await engine.match_related_reports(
        source,
        [other],
    )

    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].candidate_report_id == 2


@pytest.mark.asyncio
async def test_rank_cap_duplicate_and_self_filter():
    pool = [SOURCE, candidate(), candidate(), replace(SOURCE, report_id=3, description=None)]
    outcome = await engine.match_related_reports(SOURCE, pool, engine.MatchingRules(result_limit=1))
    assert [m.candidate_report_id for m in outcome.candidates] == [2]


@pytest.mark.asyncio
async def test_timezone_offsets_compare_the_same_instant():
    same_instant = NOW.astimezone(timezone(timedelta(hours=8)))
    match, = (await engine.match_related_reports(SOURCE, [candidate(observed_at=same_instant)])).candidates
    assert "close_observation_time" in {s.code for s in match.signals}


def mock_repository(monkeypatch):
    repo = engine.the_repository
    for name, result in {
        "get_report_comparison_facts": SOURCE.__dict__, "begin_detection_run": 7,
        "list_candidate_comparison_facts": [candidate().__dict__], "save_detection_candidates": 1,
        "finish_detection_run": None,
        "get_latest_detection_run": None,
    }.items():
        monkeypatch.setattr(repo, name, AsyncMock(return_value=result))
    monkeypatch.setattr(engine.image_embedding_repository, "list_image_inputs", AsyncMock(return_value=[]))
    return repo


@pytest.mark.asyncio
async def test_completed_analysis_persists_suggestions_without_deciding(monkeypatch):
    repo = mock_repository(monkeypatch)
    db = AsyncMock()
    assert await engine.run_related_incident_detection(db, SOURCE.report_reference) == DetectionRunState.COMPLETED
    assert db.commit.await_count == 2
    assert repo.save_detection_candidates.await_args.kwargs["candidates"][0].candidate_report_id == 2
    repo.finish_detection_run.assert_awaited_once_with(db=db, run_id=7, run_state=DetectionRunState.COMPLETED,
                                                     image_analysis_state=engine.ImageAnalysisState.NO_SOURCE_IMAGES)


@pytest.mark.asyncio
async def test_overlapping_run_does_not_delete_or_replace_results(monkeypatch):
    repo = mock_repository(monkeypatch)
    repo.begin_detection_run.return_value = None
    assert await engine.run_related_incident_detection(AsyncMock(), "RC-0001") == DetectionRunState.PROCESSING
    repo.save_detection_candidates.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_marks_analysis_unavailable_without_exposing_text(monkeypatch, caplog):
    repo = mock_repository(monkeypatch)
    monkeypatch.setattr(engine, "match_related_reports", AsyncMock(side_effect=TimeoutError("PRIVATE DESCRIPTION")))
    assert await engine.run_related_incident_detection(AsyncMock(), "RC-0001") == DetectionRunState.FAILED
    assert repo.finish_detection_run.await_args.kwargs["run_state"] == DetectionRunState.FAILED
    assert "PRIVATE DESCRIPTION" not in caplog.text


@pytest.mark.asyncio
async def test_failure_cleanup_also_failing_does_not_escape(monkeypatch):
    repo = mock_repository(monkeypatch)
    repo.begin_detection_run.side_effect = RuntimeError("DB unavailable")
    db = AsyncMock()
    db.rollback.side_effect = RuntimeError("Rollback unavailable")
    assert await engine.run_related_incident_detection(db, "RC-0001") == DetectionRunState.FAILED


@pytest.mark.asyncio
async def test_background_detection_enables_embedding_generation(
    monkeypatch,
):

    from contextlib import (
        asynccontextmanager,
    )

    run = AsyncMock()

    @asynccontextmanager
    async def session():
        yield AsyncMock()

    monkeypatch.setattr(
        engine,
        "AsyncSessionLocal",
        session,
    )

    monkeypatch.setattr(
        engine,
        "run_related_incident_detection",
        run,
    )

    await (
        engine
        .run_related_incident_detection_in_background(
            "RC-0001"
        )
    )

    assert (
        run.await_args.kwargs[
            "report_reference"
        ]
        == "RC-0001"
    )

    assert (
        run.await_args.kwargs[
            "generate_embeddings"
        ]
        is True
    )
