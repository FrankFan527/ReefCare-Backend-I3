from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import related_incident_worker as worker
from app.schemas.related_incident import DetectionRunState


@pytest.mark.asyncio
async def test_worker_caches_all_sources_before_matching_any_report(monkeypatch):
    events = []
    async def references(batch_size):
        for report_id in (1,2):
            yield {"report_id":report_id,"report_reference":f"RC-{report_id}"}
    @asynccontextmanager
    async def session():
        yield AsyncMock()
    async def inputs(db,ids,limit):
        return [{"report_id":ids[0]}]
    async def generate(db,rows):
        events.append(("cache",rows[0]["report_id"]))
    async def analyse(db,reference,**kwargs):
        events.append(("analyse",reference))
        assert kwargs["generate_embeddings"] is False
        return DetectionRunState.COMPLETED
    monkeypatch.setattr(worker,"references",references)
    monkeypatch.setattr(worker,"AsyncSessionLocal",session)
    monkeypatch.setattr(worker.repository,"list_image_inputs",inputs)
    monkeypatch.setattr(worker,"generate_missing_embeddings",generate)
    monkeypatch.setattr(worker,"run_related_incident_detection",analyse)
    assert await worker.sweep() == 0
    assert events == [("cache",1),("cache",2),("analyse","RC-1"),("analyse","RC-2")]


@pytest.mark.asyncio
async def test_worker_reports_missing_model_before_accessing_database(monkeypatch,caplog):
    def missing(path):
        raise FileNotFoundError("PRIVATE/path")
    monkeypatch.setattr(worker,"_load_model",missing)
    sweep = AsyncMock()
    monkeypatch.setattr(worker,"sweep",sweep)
    args = SimpleNamespace(once=True,cached_only=False,batch_size=100,interval=60)
    assert await worker.main(args) == 1
    sweep.assert_not_awaited()
    assert "PRIVATE" not in caplog.text
