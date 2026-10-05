import math
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.schemas.related_incident import ImageEmbedding, ImageAnalysisState
from app.services import image_embedding_service as images
from app.services import related_incident_detection_service as engine
from tests.unit.test_related_incident_detection import SOURCE, candidate, mock_repository


def vector(first=1.0, second=0.0):
    return (first, second, *([0.0]*510))


def embedding(evidence_id=1, values=None, model=images.IMAGE_MODEL, version=images.IMAGE_VERSION):
    return ImageEmbedding(evidence_id, values or vector(), model, version)


def image_row(report_id=1, evidence_id=1, **changes):
    return {"report_id": report_id, "evidence_id": evidence_id, "file_reference": "PRIVATE/storage-key",
            "uploaded_at": datetime(2026,10,4,tzinfo=timezone.utc),
            "image_embedding": vector(), "image_embedding_model": images.IMAGE_MODEL,
            "image_embedding_version": images.IMAGE_VERSION,
            "image_embedding_generated_at": datetime(2026,10,4,tzinfo=timezone.utc), **changes}


@pytest.mark.parametrize("values", [None, [], [1,2], "secret", vector(float("nan")), vector(float("inf")), vector(0,0)])
def test_invalid_arrays_are_not_matches(values):
    assert images.normalise_vector(values) is None


def test_vectors_are_unit_normalised():
    result = images.normalise_vector(vector(3,4))
    assert result[:2] == (0.6,0.8)
    assert math.isclose(sum(value*value for value in result),1)


@pytest.mark.parametrize("change", [{"image_embedding_model":"another-model"}, {"image_embedding_version":"v2"},
                                     {"image_embedding_generated_at":None}])
def test_incompatible_or_untracked_features_are_ignored(change):
    assert images.embedding_from_row(image_row(**change)) is None


def test_exact_knn_groups_best_pair_and_limits_neighbours():
    source = replace(SOURCE,image_embeddings=(embedding(),))
    pool = [candidate(image_embeddings=(embedding(2,vector(.8,.6)),)),
            replace(candidate(),report_id=3,image_embeddings=(embedding(3),embedding(4))),
            replace(candidate(),report_id=4,image_embeddings=(embedding(5,vector(0,1)),))]
    assert images.nearest_image_reports(source,pool,top_k=1) == {3:1.0}
    scores = images.nearest_image_reports(source,pool,top_k=10)
    assert math.isclose(scores[2],.8) and scores[3] == 1 and scores[4] == 0
    assert images.nearest_image_reports(source,[replace(candidate(),image_embeddings=(embedding(model="old"),))]) == {}


@pytest.mark.asyncio
async def test_image_score_is_persistable_explainable_and_bounded():
    source = replace(SOURCE,image_embeddings=(embedding(),))
    other = candidate(image_embeddings=(embedding(2),embedding(3)))
    match, = (await engine.match_related_reports(source,[other])).candidates
    assert match.similarity_score == 1
    signal, = [signal for signal in match.signals if signal.code == "similar_image"]
    assert signal.signal_score == 1 and float(signal.signal_weight) == .15
    assert math.isclose(sum(float(s.signal_score*s.signal_weight) for s in match.signals), float(match.similarity_score))
    assert "PRIVATE" not in str(match.signals) and "vector" not in str(match.signals)


@pytest.mark.asyncio
async def test_identical_images_cannot_override_threat_or_location():
    source = replace(SOURCE,image_embeddings=(embedding(),))
    for other in [candidate(threat_category_code="different",image_embeddings=(embedding(2),)),
                  candidate(dive_site_id=20,public_area_label="different",image_embeddings=(embedding(2),))]:
        assert (await engine.match_related_reports(source,[other])).candidates == []


@pytest.mark.asyncio
async def test_noneligible_neighbours_do_not_consume_knn_slots():
    source = replace(SOURCE,image_embeddings=(embedding(),))
    far = candidate(dive_site_id=99,public_area_label="far",image_embeddings=(embedding(2),))
    near = replace(candidate(image_embeddings=(embedding(3,vector(.8,.6)),)),report_id=3)
    matches = (await engine.match_related_reports(source,[far,near],engine.MatchingRules(image_top_k=1))).candidates
    assert [match.candidate_report_id for match in matches] == [3]
    assert "similar_image" in {s.code for s in matches[0].signals}


@pytest.mark.asyncio
async def test_weak_area_can_use_image_corroboration_but_never_high():
    source = replace(SOURCE,dive_site_id=None,description=None,image_embeddings=(embedding(),))
    match, = (await engine.match_related_reports(source,[replace(source,report_id=2)])).candidates
    assert match.relatedness_level.value != "high"
    assert "similar_image" in {s.code for s in match.signals}


@pytest.mark.parametrize("rows,state", [
    ([],ImageAnalysisState.NO_SOURCE_IMAGES),
    ([image_row(image_embedding=None)],ImageAnalysisState.UNAVAILABLE),
    ([image_row()],ImageAnalysisState.INSUFFICIENT_HISTORY),
    ([image_row(),image_row(2,2)],ImageAnalysisState.READY),
    ([image_row(),image_row(2,2),image_row(2,3,image_embedding_model="old")],ImageAnalysisState.PARTIAL),
])
def test_image_availability_is_explicit(rows,state):
    assert images.attach_embeddings(SOURCE,[candidate()],rows)[2] == state


@pytest.mark.asyncio
async def test_download_failure_preserves_text_matching_and_private_keys(monkeypatch,caplog):
    monkeypatch.setattr(images,"_download_and_embed",lambda key: (_ for _ in ()).throw(RuntimeError(key)))
    save = AsyncMock()
    monkeypatch.setattr(images.repository,"save_embedding",save)
    row = image_row(image_embedding=None)
    result = await images.generate_missing_embeddings(AsyncMock(),[row])
    assert result[0]["image_embedding"] is None
    assert "PRIVATE" not in caplog.text
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_unchanged_snapshot_skips_rerun_but_new_photo_creates_version(monkeypatch):
    repo = mock_repository(monkeypatch)
    fingerprint = engine._input_fingerprint(SOURCE,[candidate()],[],engine.MatchingRules())
    repo.get_latest_detection_run.return_value = {"run_state":"completed","rule_version":engine.RULE_VERSION,
                                                  "input_fingerprint":fingerprint}
    assert await engine.run_related_incident_detection(AsyncMock(),"RC-0001") == engine.DetectionRunState.COMPLETED
    repo.begin_detection_run.assert_not_awaited()
    monkeypatch.setattr(engine.image_embedding_repository,"list_image_inputs",AsyncMock(return_value=[image_row()]))
    assert await engine.run_related_incident_detection(AsyncMock(),"RC-0001") == engine.DetectionRunState.COMPLETED
    assert repo.begin_detection_run.await_args.kwargs["input_fingerprint"] != fingerprint


@pytest.mark.asyncio
async def test_generation_timeout_still_completes_text_detection(monkeypatch):
    repo = mock_repository(monkeypatch)
    monkeypatch.setattr(engine.image_service,"generate_missing_embeddings",AsyncMock(side_effect=TimeoutError()))
    state = await engine.run_related_incident_detection(AsyncMock(),"RC-0001",generate_embeddings=True)
    assert state == engine.DetectionRunState.COMPLETED
    assert repo.finish_detection_run.await_args.kwargs["image_analysis_state"] == ImageAnalysisState.NO_SOURCE_IMAGES
