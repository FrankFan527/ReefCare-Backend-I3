# ---------------------------------------------------------------------------
# US7.1 / US7.2 follow-up — integration test against a real database.
#
# Run only where i3_e7_follow_up.sql is applied, with DATABASE_URL pointed at
# the RESTRICTED login role (reefcare_api), so the grants are exercised the
# way production uses them:
#
#   pytest -m integration tests/integration/test_follow_up_db.py
#
# Everything runs inside one outer transaction that is rolled back, so the
# branch is left exactly as it was.
# ---------------------------------------------------------------------------

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import WorkflowError
from app.schemas.follow_up import (
    FollowUpCorrection,
    FollowUpCreate,
    FollowUpState,
    FollowUpType,
    MonitoringCreate,
)
from app.services import follow_up_service as the_service


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def the_session():
    if settings.app_env.lower() == "production":
        pytest.skip("Never run the follow-up integration test against production")

    the_engine = create_async_engine(settings.database_url, poolclass=NullPool)

    async with the_engine.connect() as the_connection:
        the_outer_transaction = await the_connection.begin()

        the_db = AsyncSession(
            bind=the_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            the_migrated = (
                await the_db.execute(
                    text("SELECT to_regclass('monitoring_condition') IS NOT NULL")
                )
            ).scalar_one()

            if not the_migrated:
                pytest.skip("i3_e7_follow_up.sql is not applied on this database")

            yield the_db

        finally:
            await the_db.close()
            await the_outer_transaction.rollback()

    await the_engine.dispose()


async def find_case_in_status(
    the_db: AsyncSession,
    the_status_code: str,
) -> dict | None:
    """
    A live report in the wanted status, claimed by an active Coordinator.
    The Coordinator is adopted as the owner for the test, inside the
    transaction that is rolled back.
    """

    the_coordinator = (
        await the_db.execute(text(
            """
            SELECT u.user_id FROM app_user AS u
            JOIN app_role AS r ON r.role_id = u.role_id
            WHERE r.code = 'case_coordinator' AND u.is_active
            ORDER BY u.user_id LIMIT 1
            """
        ))
    ).scalar_one_or_none()

    if the_coordinator is None:
        return None

    the_report = (
        await the_db.execute(text(
            """
            SELECT r.report_reference
            FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE cs.code = :status_code AND r.deleted_at IS NULL
            ORDER BY r.report_id LIMIT 1
            """
        ), {"status_code": the_status_code})
    ).scalar_one_or_none()

    if the_report is None:
        return None

    await the_db.execute(
        text(
            """
            UPDATE report
            SET claimed_by_user_id = :coordinator_id,
                claimed_at = coalesce(claimed_at, now())
            WHERE report_reference = :report_reference
            """
        ),
        {"coordinator_id": the_coordinator, "report_reference": the_report},
    )

    return {"coordinator_id": the_coordinator, "report_reference": the_report}


@pytest.mark.asyncio
async def test_monitoring_visit_round_trip(the_session):
    the_case = await find_case_in_status(the_session, "evidence_accepted")

    if the_case is None:
        pytest.skip("No evidence_accepted report available on this database")

    the_reference = the_case["report_reference"]
    the_coordinator_id = the_case["coordinator_id"]

    the_status_before = (
        await the_session.execute(text(
            """
            SELECT cs.code FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE r.report_reference = :ref
            """
        ), {"ref": the_reference})
    ).scalar_one()

    the_saved = await the_service.record_monitoring(
        the_session, the_reference, the_coordinator_id,
        MonitoringCreate(
            action_date="2026-10-01",
            condition_code="improving",
            observations="Net gone, coral still bare but recovering",
            next_follow_up_required=False,
        ),
    )

    assert the_saved.follow_up_type == FollowUpType.MONITORING
    assert the_saved.condition_code == "improving"
    assert the_saved.condition_reviewed_by_name is not None
    assert the_saved.next_follow_up_required is False
    assert the_saved.next_follow_up_date is None

    # US7.2: a monitoring visit does not move the case
    the_status_after = (
        await the_session.execute(text(
            """
            SELECT cs.code FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE r.report_reference = :ref
            """
        ), {"ref": the_reference})
    ).scalar_one()

    assert the_status_after == the_status_before

    # and it appears in the history
    the_history = await the_service.list_follow_ups_for_owned_case(
        the_session, the_reference, the_coordinator_id
    )

    assert the_history.total >= 1
    assert the_saved.case_action_id in {i.case_action_id for i in the_history.items}

    # a second visit is allowed: monitoring repeats (AC5)
    the_second = await the_service.record_monitoring(
        the_session, the_reference, the_coordinator_id,
        MonitoringCreate(
            action_date="2026-10-03",
            condition_code="stable",
            observations="No further change",
            next_follow_up_required=True,
            next_follow_up_date="2026-12-01",
        ),
    )

    assert the_second.next_follow_up_date is not None
    assert the_second.case_action_id != the_saved.case_action_id


@pytest.mark.asyncio
async def test_sourced_outcome_does_not_move_a_referred_case(the_session):
    the_case = await find_case_in_status(the_session, "referred")

    if the_case is None:
        pytest.skip("No referred report available on this database")

    the_reference = the_case["report_reference"]
    the_coordinator_id = the_case["coordinator_id"]

    the_saved = await the_service.record_follow_up(
        the_session, the_reference, the_coordinator_id,
        FollowUpCreate(
            follow_up_type=FollowUpType.SOURCED_OUTCOME,
            follow_up_state=FollowUpState.OUTCOME_RECORDED,
            action_type_code="authority_notified",
            recording_level="externally_sourced",
            action_date="2026-10-02",
            source_reference="Tioman Marine Park office, email 2026-10-02",
            recorded_outcome="Park team removed the gear",
        ),
    )

    assert the_saved.follow_up_type == FollowUpType.SOURCED_OUTCOME
    assert the_saved.source_reference is not None

    # US7.1 AC5: the referral is still a referral
    the_status = (
        await the_session.execute(text(
            """
            SELECT cs.code FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE r.report_reference = :ref
            """
        ), {"ref": the_reference})
    ).scalar_one()

    assert the_status == "referred"

    # monitoring is not appropriate on a referred case
    with pytest.raises(WorkflowError):
        await the_service.record_monitoring(
            the_session, the_reference, the_coordinator_id,
            MonitoringCreate(
                action_date="2026-10-03",
                condition_code="stable",
                observations="Should not be allowed here",
            ),
        )


@pytest.mark.asyncio
async def test_correction_appends_rather_than_overwrites(the_session):
    the_case = await find_case_in_status(the_session, "response_planned")

    if the_case is None:
        pytest.skip("No response_planned report available on this database")

    the_reference = the_case["report_reference"]
    the_coordinator_id = the_case["coordinator_id"]

    the_original = await the_service.record_follow_up(
        the_session, the_reference, the_coordinator_id,
        FollowUpCreate(
            follow_up_type=FollowUpType.ACTION,
            follow_up_state=FollowUpState.ACTION_PLANNED,
            action_type_code="debris_cleanup",
            responsible_team="Reef team",
            notes="Planned for next week",
        ),
    )

    the_correction = await the_service.correct_follow_up(
        the_session, the_reference, the_original.case_action_id, the_coordinator_id,
        FollowUpCorrection(
            responsible_team="Marine park team",
            correction_reason="Wrong team recorded",
        ),
    )

    assert the_correction.case_action_id != the_original.case_action_id
    assert the_correction.supersedes_case_action_id == the_original.case_action_id
    assert the_correction.responsible_team == "Marine park team"

    # the original is still there, and the default history shows only the latest
    the_current = await the_service.list_follow_ups_for_owned_case(
        the_session, the_reference, the_coordinator_id
    )
    the_full = await the_service.list_follow_ups_for_owned_case(
        the_session, the_reference, the_coordinator_id, include_superseded=True
    )

    the_current_ids = {i.case_action_id for i in the_current.items}
    the_full_ids = {i.case_action_id for i in the_full.items}

    assert the_original.case_action_id not in the_current_ids
    assert the_original.case_action_id in the_full_ids

    # correcting the superseded record again is refused
    with pytest.raises(WorkflowError):
        await the_service.correct_follow_up(
            the_session, the_reference, the_original.case_action_id, the_coordinator_id,
            FollowUpCorrection(correction_reason="second attempt"),
        )

    # and the records stay append-only at the database level
    with pytest.raises(DBAPIError):
        await the_session.execute(
            text("UPDATE case_action SET notes = 'rewritten' WHERE case_action_id = :id"),
            {"id": the_original.case_action_id},
        )
