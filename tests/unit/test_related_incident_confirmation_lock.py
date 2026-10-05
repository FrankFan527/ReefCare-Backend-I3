"""Lock order and transaction ownership for the code-only US5.9 guard."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import DBAPIError

from app.repositories import related_incident_repository as repo


@pytest.mark.asyncio
async def test_shared_advisory_lock_precedes_ordered_row_locks_without_commit():
    rows = [
        {"report_id": 2, "report_reference": "RC-0002", "claimed_by_user_id": 42, "incident_id": 10},
        {"report_id": 9, "report_reference": "RC-0009", "claimed_by_user_id": 42, "incident_id": None},
    ]
    result = Mock()
    result.mappings.return_value.all.return_value = rows
    db = AsyncMock()
    db.execute.side_effect = [Mock(), result]

    locked = await repo.lock_relationship_reports(db, "RC-0009", "RC-0002")

    calls = db.execute.await_args_list
    assert str(calls[0].args[0]) == "SELECT pg_advisory_xact_lock(59590001)"
    sql = " ".join(str(calls[1].args[0]).split())
    assert "ORDER BY r.report_id FOR UPDATE OF r" in sql
    assert "r.deleted_at IS NULL" in sql
    assert calls[1].args[1] == {"report_reference": "RC-0009", "related_reference": "RC-0002"}
    assert locked == {row["report_reference"]: row for row in rows}
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_row_lock_failure_propagates_before_confirmation():
    error = DBAPIError("statement", {}, SimpleNamespace(sqlstate="42501"))
    db = AsyncMock()
    db.execute.side_effect = [Mock(), error]
    with pytest.raises(DBAPIError):
        await repo.lock_relationship_reports(db, "RC-0001", "RC-0002")
    assert db.execute.await_count == 2
    db.commit.assert_not_awaited()
