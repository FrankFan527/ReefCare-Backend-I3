from datetime import date, datetime, timezone
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import NotFoundError
from app.repositories.hotspot_repository import filter_parameters
from app.schemas.hotspot import HotspotQuery, HotspotReportsQuery
from app.services import hotspot_service as service


NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def group(site=1, threat="unsure", bucket="2026-09-01", count=1):
    return dict(site_id=site, site_name=f"Site {site}", area="Area A", region="Region A",
                threat_code=threat, threat_label=service.THREATS.get(threat, threat),
                bucket=bucket, report_count=count)


def query(**overrides):
    return HotspotQuery(**dict(observed_from="2026-09-01", observed_to="2026-09-13",
                              interval="day", **overrides))


def data(groups=(), matching=None, undated=0):
    total = sum(row["report_count"] for row in groups)
    return dict(groups=list(groups), included_report_count=total,
                matching_report_count=total if matching is None else matching,
                undated_report_count=undated, analysed_at=NOW)


def intake(owner=None, closed=False):
    return dict(report_reference="RC-001", site_id=1, site_name="Site 1", area="Area A", region="Region A",
                threat_code="unsure", threat_label="Unsure", observed_at=NOW, submitted_at=NOW,
                status_code="received", status_label="Received", is_closed=closed,
                claimed_by_user_id=owner, owner_display_name="Coordinator" if owner else None,
                description="PRIVATE DESCRIPTION", latitude=1.123456, evidence=["PRIVATE KEY"], observer_id=987)


@pytest.fixture
def db():
    return AsyncMock()


@pytest.mark.parametrize("params", [
    {"observedFrom": "2026-09-01"}, {"observedTo": "2026-09-01"},
    {"observedFrom": "2026-09-02", "observedTo": "2026-09-01"},
    {"observedFrom": "2025-01-01", "observedTo": "2026-01-02"},
    {"observedFrom": "9999-12-31", "observedTo": "9999-12-31"},
    {"observedFrom": "9999-12-01", "observedTo": "9999-12-10"},
    {"observedFrom": "0001-01-01", "observedTo": "0001-01-02"},
    {"siteId": 0}, {"threat": "ecological_risk"}, {"interval": "year"},
    {"area": "   "}, {"region": ""}, {"latitude": 1.2},
])
def test_reject_invalid_filters(params):
    with pytest.raises(ValidationError):
        HotspotQuery(**params)


def test_default_filters_are_thirty_local_calendar_days():
    filters = service.resolve_filters(HotspotQuery(), date(2026, 9, 13))
    assert filters.observed_from == date(2026, 8, 15)
    assert filters.observed_to == date(2026, 9, 13)
    assert filters.threat is None


def test_inclusive_dates_become_half_open_malaysia_boundaries():
    params = filter_parameters(service.resolve_filters(query()))
    assert params["start_at"].astimezone(timezone.utc).isoformat() == "2026-08-31T16:00:00+00:00"
    assert params["end_at"].astimezone(timezone.utc).isoformat() == "2026-09-13T16:00:00+00:00"


def test_summary_preserves_unsure_and_zero_fills_intervals():
    summary = service.build_summary([group(count=2), group(threat="ghost_gear", bucket="2026-09-03")],
                                    service.resolve_filters(query()))
    assert summary.report_count == 3
    assert sum(x.report_count for x in summary.threat_breakdown) == 3
    assert next(x for x in summary.threat_breakdown if x.code == "unsure").report_count == 2
    assert len(summary.frequency) == 13
    assert [x.report_count for x in summary.frequency[:3]] == [2, 0, 1]
    assert summary.trend_state == "available"


def test_unknown_historical_threat_is_not_dropped_from_all_threats():
    summary = service.build_summary([group(threat="legacy_code")], service.resolve_filters(query()))
    assert summary.report_count == 1
    assert next(x for x in summary.threat_breakdown if x.code == "legacy_code").report_count == 1


def test_many_reports_in_one_interval_do_not_imply_a_trend():
    summary = service.build_summary([group(count=100)], service.resolve_filters(query()))
    assert summary.trend_state == "insufficient_history"


@pytest.mark.parametrize("interval,start,end,buckets,first,last", [
    ("week", "2026-09-02", "2026-09-15", 3, "2026-08-31", "2026-09-21"),
    ("month", "2024-02-10", "2024-03-05", 2, "2024-02-01", "2024-04-01"),
])
def test_calendar_buckets_and_partial_edges(interval, start, end, buckets, first, last):
    filters = service.resolve_filters(HotspotQuery(observed_from=start, observed_to=end, interval=interval))
    summary = service.build_summary([], filters)
    assert len(summary.frequency) == buckets
    assert summary.frequency[0].bucket_start.isoformat() == first
    assert summary.frequency[-1].bucket_end_exclusive.isoformat() == last
    assert summary.frequency[0].is_partial and summary.frequency[-1].is_partial


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,state", [(data(), "no_matches"), (data(matching=2), "insufficient_data"),
                                       (data(undated=1), "insufficient_data"), (data([group()]), "ready")])
async def test_empty_insufficient_and_ready_are_distinct(db, monkeypatch, raw, state):
    monkeypatch.setattr(service.repository, "get_analysis", AsyncMock(return_value=raw))
    monkeypatch.setattr(service, "load_map_locations", lambda: ({}, False))
    result = await service.get_analysis(db, query())
    assert result.state == state
    assert result.last_successful_update_at == NOW
    assert result.data_quality.excluded_missing_site_count == raw["matching_report_count"] - raw["included_report_count"]
    assert result.summary is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [SQLAlchemyError("private connection detail"), TimeoutError()])
async def test_failure_is_not_zero_or_success(db, monkeypatch, failure):
    monkeypatch.setattr(service.repository, "get_analysis", AsyncMock(side_effect=failure))
    result = await service.get_analysis(db, query())
    assert result.state == "unavailable"
    assert result.summary is None and result.data_quality is None
    assert result.last_successful_update_at is None
    assert "private connection" not in result.model_dump_json()
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_feature_disable_never_queries_or_changes_workflow(db, monkeypatch):
    monkeypatch.setattr(service.settings, "hotspot_enabled", False)
    repo = AsyncMock()
    monkeypatch.setattr(service.repository, "get_analysis", repo)
    assert (await service.get_analysis(db, query())).state == "unavailable"
    repo.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_failure_still_returns_unavailable(db, monkeypatch):
    monkeypatch.setattr(service.repository, "get_analysis", AsyncMock(side_effect=SQLAlchemyError()))
    db.rollback.side_effect = SQLAlchemyError()
    assert (await service.get_analysis(db, query())).state == "unavailable"


@pytest.mark.asyncio
async def test_partial_map_does_not_hide_named_site_reports(db, monkeypatch):
    monkeypatch.setattr(service.repository, "get_analysis", AsyncMock(return_value=data([group(count=2), group(site=2)])))
    location = service.GeneralisedMapLocation(latitude=1.2, longitude=104.1, uncertainty_metres=2000, basis="Generalised area")
    monkeypatch.setattr(service, "load_map_locations", lambda: ({1: location}, False))
    result = await service.get_analysis(db, query())
    assert result.state == "ready" and result.map_state == "partial"
    assert result.summary.report_count == 3
    assert result.data_quality.mapped_report_count == 2
    assert result.data_quality.unmapped_report_count == 1
    assert sum(x.report_count for x in result.sites) == 3


@pytest.mark.asyncio
async def test_broken_map_preserves_analysis(db, monkeypatch):
    monkeypatch.setattr(service.repository, "get_analysis", AsyncMock(return_value=data([group()])))
    monkeypatch.setattr(service, "load_map_locations", lambda: ({}, True))
    result = await service.get_analysis(db, query())
    assert result.state == "ready" and result.map_state == "unavailable"
    assert result.summary.report_count == 1


def test_only_explicit_generalised_config_provides_map_coordinates(tmp_path, monkeypatch):
    path = tmp_path / "map.json"
    monkeypatch.setattr(service.settings, "hotspot_map_config", str(path))
    assert service.load_map_locations() == ({}, False)
    config = {"sites": [{"siteId": 1, "approvedGeneralised": True, "latitude": 1.2, "longitude": 104.1,
                         "uncertaintyMetres": 2000, "basis": "Approved generalised site area"}]}
    path.write_text(json.dumps(config))
    locations, failed = service.load_map_locations()
    assert not failed and locations[1].latitude == 1.2
    config["sites"][0]["latitude"] = 1.123456
    path.write_text(json.dumps(config))
    assert service.load_map_locations() == ({}, True)


@pytest.mark.parametrize("owner,closed,ownership,action", [
    (None, False, "unclaimed", "claim"), (12, False, "mine", "review"),
    (12, True, "mine", "review"), (99, False, "other", "assigned_summary"),
    (99, True, "other", "assigned_summary"), (None, True, "unclaimed", "restricted_summary"),
])
def test_claim_first_navigation_and_safe_projection(owner, closed, ownership, action):
    result = service.project_intake(intake(owner, closed), 12)
    assert result.ownership == ownership and result.next_action == action
    assert bool(result.claim_api_path) == (action == "claim")
    assert bool(result.review_api_path) == (action == "review")
    payload = result.model_dump_json()
    for protected in ("PRIVATE", "latitude", "observerId", "evidence", "description", "claimedByUserId"):
        assert protected not in payload


@pytest.mark.asyncio
async def test_out_of_range_page_retains_total(db, monkeypatch):
    monkeypatch.setattr(service.repository, "list_reports", AsyncMock(return_value={"items": [], "total": 7}))
    result = await service.get_reports(db, HotspotReportsQuery(page=99), 12)
    assert result.state == "ready" and result.total == 7 and result.items == []


@pytest.mark.asyncio
async def test_context_uses_owned_site_and_observation_period(db, monkeypatch):
    row = intake(12)
    # A late-night UTC timestamp belongs to the following Malaysia date.
    row["observed_at"] = datetime(2025, 3, 10, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(service.repository, "get_owned_context", AsyncMock(return_value=row))
    repo = AsyncMock(return_value=data([group(bucket="2025-03-10")]))
    monkeypatch.setattr(service.repository, "get_analysis", repo)
    result = await service.get_case_context(db, "RC-001", 12)
    assert result.filters.site_id == 1 and result.filters.observed_to == date(2025, 3, 11)
    assert "observedTo=2025-03-11" in result.analysis_query
    assert result.analysis_api_path.endswith(result.analysis_query)
    assert repo.call_args.kwargs["filters"] == result.filters


@pytest.mark.asyncio
async def test_nonowned_context_never_runs_analysis(db, monkeypatch):
    monkeypatch.setattr(service.repository, "get_owned_context", AsyncMock(return_value=None))
    repo = AsyncMock()
    monkeypatch.setattr(service.repository, "get_analysis", repo)
    with pytest.raises(NotFoundError):
        await service.get_case_context(db, "RC-001", 99)
    repo.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_missing_geography_or_time_has_no_link(db, monkeypatch):
    row = intake(12)
    row["observed_at"] = None
    monkeypatch.setattr(service.repository, "get_owned_context", AsyncMock(return_value=row))
    result = await service.get_case_context(db, "RC-001", 12)
    assert result.state == "insufficient_data" and result.analysis_api_path is None
