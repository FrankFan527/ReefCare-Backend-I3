"""Export actual repository statements/parameters and synthetic expectations.

Usage: python scripts/export_hotspot_sql_checks.py > tmp/hotspot-sql-checks.json
Does not connect to a database or load application credentials.
"""

import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy.dialects.postgresql import dialect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.repositories import hotspot_repository as repository
from app.schemas.hotspot import HotspotFilters


class CaptureResult:
    def mappings(self):
        return self

    def one(self):
        return {}

    def first(self):
        return None

    def all(self):
        return []


class CaptureSession:
    async def execute(self, statement, params=None):
        compiled = statement.compile(dialect=dialect(paramstyle="numeric_dollar"))
        self.query = {"sql": str(compiled), "params": [(params or {})[key] for key in compiled.positiontup]}
        return CaptureResult()


async def main():
    db, checks = CaptureSession(), []
    filters = dict(observed_from="2026-09-01", observed_to="2026-09-13", interval="day")

    async def capture(name, function, expected, **kwargs):
        await function(db, **kwargs)
        checks.append(dict(name=name, **db.query, expected=expected))

    for name, extras, expected in [
        ("all", {}, {"matching": 7, "included": 5, "undated": 1, "unsure": 2}),
        ("site", {"site_id": 1}, {"matching": 3, "included": 3, "undated": 1, "unsure": 2}),
        ("area", {"area": "Area A"}, {"matching": 4, "included": 4, "undated": 1, "unsure": 2}),
        ("region", {"region": "Region B"}, {"matching": 3, "included": 2, "undated": 0, "unsure": 0}),
        ("combined", {"site_id": 1, "area": "Area A", "region": "Region A", "threat": "unsure"},
         {"matching": 2, "included": 2, "undated": 1, "unsure": 2}),
        ("unsure", {"threat": "unsure"}, {"matching": 4, "included": 2, "undated": 1, "unsure": 2}),
        ("empty", {"area": "Area A", "site_id": 2}, {"matching": 0, "included": 0, "undated": 0, "unsure": 0}),
        ("injection", {"area": "Area A' OR TRUE --"}, {"matching": 0, "included": 0, "undated": 0, "unsure": 0}),
    ]:
        await capture(name, repository.get_analysis, expected, filters=HotspotFilters(**filters, **extras))
    for interval in ("week", "month"):
        await capture(interval, repository.get_analysis, {"matching": 7, "included": 5, "undated": 1, "unsure": 2},
                      filters=HotspotFilters(**{**filters, "interval": interval}))
    for page, expected in [(1, ["RC-003", "RC-011"]), (2, ["RC-002", "RC-012"]), (3, ["RC-001"]), (4, [])]:
        await capture(f"page{page}", repository.list_reports, {"total": 5, "references": expected},
                      filters=HotspotFilters(**filters), page=page, page_size=2)
    await capture("owned", repository.get_owned_context, {"rows": 1}, report_reference="RC-002", coordinator_id=12)
    await capture("not_owned", repository.get_owned_context, {"rows": 0}, report_reference="RC-002", coordinator_id=99)
    await capture("deleted_context", repository.get_owned_context, {"rows": 0}, report_reference="RC-008", coordinator_id=12)
    await capture("intake", repository.get_intake, {"rows": 1}, report_reference="RC-003")
    await capture("draft_intake", repository.get_intake, {"rows": 0}, report_reference="RC-009")
    await capture("deleted_intake", repository.get_intake, {"rows": 0}, report_reference="RC-008")
    await capture("sites", repository.list_sites, {"rows": 3})
    fixture = Path(__file__).resolve().parents[1] / "tests/sql/hotspots.fixture.sql"
    print(json.dumps({"fixture": fixture.read_text(), "checks": checks}, default=lambda value: value.isoformat()))


asyncio.run(main())
