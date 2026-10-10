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
from app.core.exceptions import AuthorizationError, WorkflowError
from app.repositories import public_context_repository
from app.schemas.follow_up import (
    FollowUpCorrection,
    FollowUpCreate,
    FollowUpPublication,
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


async def assert_case_action_is_append_only_for_the_app(
    the_db: AsyncSession,
    the_case_action_id: int,
) -> None:
    """
    case_action is append-only for the application, checked in a way that
    does not depend on the role this test connects as.

    1. reefcare_app (the role the API login inherits from) must not hold
       UPDATE on case_action. This holds on every database, so a branch where
       someone granted UPDATE fails here instead of passing quietly.
    2. If the connected role cannot UPDATE either (the documented way to run
       this file, as reefcare_api), a direct UPDATE must really be refused.
       Run last: the refusal aborts the transaction, which is rolled back.
    """

    the_app_role_exists = (
        await the_db.execute(text("SELECT to_regrole('reefcare_app') IS NOT NULL"))
    ).scalar_one()

    if the_app_role_exists:
        the_app_role_can_update = (
            await the_db.execute(text(
                "SELECT has_table_privilege('reefcare_app', 'case_action', 'UPDATE')"
            ))
        ).scalar_one()

        assert the_app_role_can_update is False, (
            "reefcare_app holds UPDATE on case_action; follow-up history must be "
            "append-only (SELECT, INSERT only)"
        )

    the_connected_role_can_update = (
        await the_db.execute(text(
            "SELECT has_table_privilege(current_user, 'case_action', 'UPDATE')"
        ))
    ).scalar_one()

    if the_connected_role_can_update:
        # connected as the owner or another privileged role: grants do not
        # apply to it, so a direct UPDATE proves nothing about the app
        return

    with pytest.raises(DBAPIError):
        await the_db.execute(
            text("UPDATE case_action SET notes = 'rewritten' WHERE case_action_id = :id"),
            {"id": the_case_action_id},
        )


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

    # and the records stay append-only at the database level.
    #
    # The rule is a grant: the runtime role gets SELECT and INSERT on
    # case_action and nothing else. Whether a direct UPDATE is refused
    # therefore depends on who this test connects as. The table owner
    # (neondb_owner) bypasses grants, which is why the QA run reported
    # "DID NOT RAISE". So the grant itself is checked first, whoever is
    # connected, and the UPDATE is only attempted where it must fail.
    await assert_case_action_is_append_only_for_the_app(
        the_session, the_original.case_action_id
    )


@pytest.mark.asyncio
async def test_publication_is_owner_only_append_only_and_reset_by_correction(the_session):
    the_case = await find_case_in_status(the_session, "referred")

    if the_case is None:
        pytest.skip("No referred report available on this database")

    the_reference = the_case["report_reference"]
    the_coordinator_id = the_case["coordinator_id"]

    the_site_id = (
        await the_session.execute(text(
            """
            SELECT dsn.dive_site_id FROM report AS r
            JOIN dive_session AS dsn ON dsn.dive_session_id = r.dive_session_id
            WHERE r.report_reference = :ref
            """
        ), {"ref": the_reference})
    ).scalar_one_or_none()

    if the_site_id is None:
        pytest.skip("The referred report has no dive site")

    async def public_summaries() -> list[dict]:
        return await public_context_repository.list_publishable_activity(
            the_session, the_site_id,
        )

    the_outcome = await the_service.record_follow_up(
        the_session, the_reference, the_coordinator_id,
        FollowUpCreate(
            follow_up_type=FollowUpType.SOURCED_OUTCOME,
            follow_up_state=FollowUpState.OUTCOME_RECORDED,
            action_type_code="authority_notified",
            recording_level="externally_sourced",
            action_date="2026-10-02",
            source_reference="Private contact: park officer, email 2026-10-02",
            responsible_team="Named private team",
            recorded_outcome="QA publication test outcome",
        ),
    )

    # private by default
    assert the_outcome.is_publishable is False
    assert "QA publication test outcome" not in {a["summary"] for a in await public_summaries()}

    # another coordinator cannot publish it
    the_other_coordinator = (
        await the_session.execute(text(
            """
            SELECT u.user_id FROM app_user AS u
            JOIN app_role AS r ON r.role_id = u.role_id
            WHERE r.code = 'case_coordinator' AND u.is_active AND u.user_id <> :me
            ORDER BY u.user_id LIMIT 1
            """
        ), {"me": the_coordinator_id})
    ).scalar_one_or_none()

    if the_other_coordinator is not None:
        with pytest.raises(AuthorizationError):
            await the_service.set_follow_up_publication(
                the_session, the_reference, the_outcome.case_action_id,
                the_other_coordinator, FollowUpPublication(publish=True),
            )

    # the owner publishes: a superseding copy, published, case not moved
    the_published = await the_service.set_follow_up_publication(
        the_session, the_reference, the_outcome.case_action_id,
        the_coordinator_id, FollowUpPublication(publish=True),
    )

    assert the_published.is_publishable is True
    assert the_published.supersedes_case_action_id == the_outcome.case_action_id
    assert the_published.status_code.value == "referred"

    the_public = [a for a in await public_summaries() if a["summary"] == "QA publication test outcome"]
    assert len(the_public) == 1

    # only the safe fields reach the public view
    assert the_public[0]["source_label"] == "Reported by an external organisation"
    assert "Named private team" not in str(the_public[0])
    assert "Private contact" not in str(the_public[0])

    # a correction is created unpublished, so the changed outcome is not public
    the_corrected = await the_service.correct_follow_up(
        the_session, the_reference, the_published.case_action_id, the_coordinator_id,
        FollowUpCorrection(
            recorded_outcome="QA publication test outcome, corrected",
            correction_reason="Outcome wording corrected",
        ),
    )

    assert the_corrected.is_publishable is False
    the_summaries = {a["summary"] for a in await public_summaries()}
    assert "QA publication test outcome" not in the_summaries
    assert "QA publication test outcome, corrected" not in the_summaries

    # the superseded version can no longer be published or withdrawn
    with pytest.raises(WorkflowError):
        await the_service.set_follow_up_publication(
            the_session, the_reference, the_published.case_action_id,
            the_coordinator_id, FollowUpPublication(publish=False),
        )

    # republish the corrected version, then withdraw it
    the_republished = await the_service.set_follow_up_publication(
        the_session, the_reference, the_corrected.case_action_id,
        the_coordinator_id, FollowUpPublication(publish=True),
    )
    assert "QA publication test outcome, corrected" in {a["summary"] for a in await public_summaries()}

    the_withdrawn = await the_service.set_follow_up_publication(
        the_session, the_reference, the_republished.case_action_id,
        the_coordinator_id, FollowUpPublication(publish=False, publication_note="Partner asked"),
    )
    assert the_withdrawn.is_publishable is False
    assert "QA publication test outcome, corrected" not in {a["summary"] for a in await public_summaries()}

    # the full history keeps every version
    the_full = await the_service.list_follow_ups_for_owned_case(
        the_session, the_reference, the_coordinator_id, include_superseded=True
    )
    the_ids = {i.case_action_id for i in the_full.items}
    for the_record in (the_outcome, the_published, the_corrected, the_republished, the_withdrawn):
        assert the_record.case_action_id in the_ids


@pytest.mark.asyncio
async def test_a_follow_up_photo_stays_with_the_record_after_a_correction(the_session):
    """
    QA (Rifdhan, 10 Oct). A correction appends a record with a new history
    event, so a photo linked to the original's event used to vanish from the
    current record. It now follows the version chain.

    The evidence row points at a placeholder key and no file is stored; the
    whole test is rolled back.
    """

    from app.repositories.case_action_repository import save_action_evidence

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
        ),
    )

    the_photo = await save_action_evidence(
        db=the_session,
        report_reference=the_reference,
        case_event_id=the_original.case_event_id,
        uploaded_by_user_id=the_coordinator_id,
        file_reference="integration-test/not-a-real-file.jpg",
        file_size_bytes=1234,
    )

    the_correction = await the_service.correct_follow_up(
        the_session, the_reference, the_original.case_action_id, the_coordinator_id,
        FollowUpCorrection(
            responsible_team="Marine park team",
            correction_reason="Wrong team recorded",
        ),
    )

    assert the_correction.case_event_id != the_original.case_event_id

    the_current = await the_service.get_follow_up_for_owned_case(
        the_session, the_reference, the_correction.case_action_id, the_coordinator_id
    )

    assert the_photo["evidence_id"] in [
        the_item.evidence_id for the_item in the_current.evidence
    ]
