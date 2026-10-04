# ---------------------------------------------------------------------------
# US5.9 Related Incidents — integration test against a real database.
#
# Run only on a dev branch where i3_e5_related_incidents.sql is applied,
# with DATABASE_URL set to the RESTRICTED login role (reefcare_api), not
# neondb_owner, so grants are tested the way production uses them:
#
#   pytest -m integration tests/integration/test_related_incident_db.py
#
# Everything happens inside one outer transaction that is rolled back at the
# end. Service-level commits become savepoints, so not even the append-only
# decision rows survive the test.
# ---------------------------------------------------------------------------

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.schemas.related_incident import (
    CandidateDecisionState,
    CandidateMatch,
    CandidateOwnershipState,
    CandidateSignal,
    DetectionOutcome,
    DetectionRunState,
    RelatedAnalysisState,
    RelatednessLevel,
    RelationshipDecisionCreate,
)
from app.services import related_incident_detection_service as the_engine
from app.services import related_incident_service as the_service
from app.services.case_ownership_service import claim_report


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def the_session():
    if settings.app_env.lower() == "production":
        pytest.skip("Never run the related-incident integration test against production")

    the_engine_handle = create_async_engine(settings.database_url, poolclass=NullPool)

    async with the_engine_handle.connect() as the_connection:
        the_outer_transaction = await the_connection.begin()

        the_db = AsyncSession(
            bind=the_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            the_migrated = (
                await the_db.execute(text("SELECT to_regclass('related_incident_run') IS NOT NULL"))
            ).scalar_one()

            if not the_migrated:
                pytest.skip("i3_e5_related_incidents.sql is not applied on this database")

            yield the_db

        finally:
            await the_db.close()
            await the_outer_transaction.rollback()

    await the_engine_handle.dispose()


async def find_fixture_rows(the_db: AsyncSession) -> dict:
    """
    One active Coordinator, two unclaimed received reports, and (optionally)
    a report owned by a different Coordinator for the AC4 filter.
    """

    the_coordinator = (
        await the_db.execute(text(
            """
            SELECT u.user_id
            FROM app_user AS u JOIN app_role AS r ON r.role_id = u.role_id
            WHERE r.code = 'case_coordinator' AND u.is_active
            ORDER BY u.user_id LIMIT 1
            """
        ))
    ).scalar_one_or_none()

    the_unclaimed = (
        await the_db.execute(text(
            """
            SELECT r.report_id, r.report_reference
            FROM report AS r JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE r.claimed_by_user_id IS NULL AND r.deleted_at IS NULL
              AND cs.code = 'received' AND r.incident_id IS NULL
            ORDER BY r.report_id LIMIT 2
            """
        ))
    ).mappings().all()

    if the_coordinator is None or len(the_unclaimed) < 2:
        pytest.skip("Needs one active coordinator and two unclaimed received reports")

    the_other_owned = (
        await the_db.execute(text(
            """
            SELECT report_id, report_reference
            FROM report
            WHERE claimed_by_user_id IS NOT NULL
              AND claimed_by_user_id <> :coordinator_id
              AND deleted_at IS NULL
            ORDER BY report_id LIMIT 1
            """
        ), {"coordinator_id": the_coordinator})
    ).mappings().first()

    return {
        "coordinator_id": the_coordinator,
        "source": dict(the_unclaimed[0]),
        "candidate": dict(the_unclaimed[1]),
        "other_owned": dict(the_other_owned) if the_other_owned else None,
    }


async def current_status(the_db: AsyncSession, report_reference: str) -> str:
    return (
        await the_db.execute(text(
            """
            SELECT cs.code FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE r.report_reference = :ref
            """
        ), {"ref": report_reference})
    ).scalar_one()


@pytest.mark.asyncio
async def test_related_incident_end_to_end(the_session, monkeypatch):
    the_rows = await find_fixture_rows(the_session)

    the_coordinator_id = the_rows["coordinator_id"]
    the_source_ref = the_rows["source"]["report_reference"]
    the_candidate_ref = the_rows["candidate"]["report_reference"]

    # the Coordinator owns the report being reviewed
    await claim_report(the_session, the_source_ref, the_coordinator_id)

    # a stand-in matcher, so the workflow is tested before the real engine
    the_fake_matches = [
        CandidateMatch(
            candidate_report_id=the_rows["candidate"]["report_id"],
            relatedness_level=RelatednessLevel.HIGH,
            signals=[
                CandidateSignal("same_dive_site"),
                CandidateSignal("close_observation_time", "within 2 days"),
            ],
        )
    ]

    if the_rows["other_owned"] is not None:
        the_fake_matches.append(
            CandidateMatch(
                candidate_report_id=the_rows["other_owned"]["report_id"],
                relatedness_level=RelatednessLevel.MEDIUM,
                signals=[CandidateSignal("same_threat_category")],
            )
        )

    async def the_fake_matcher(the_source, the_pool):
        return DetectionOutcome(DetectionRunState.COMPLETED, the_fake_matches)

    monkeypatch.setattr(the_engine, "match_related_reports", the_fake_matcher)

    assert (
        await the_engine.run_related_incident_detection(the_session, the_source_ref)
        == DetectionRunState.COMPLETED
    )

    # AC3/AC4: only the unclaimed candidate is visible, with labelled signals
    the_list = await the_service.get_related_reports(the_session, the_source_ref, the_coordinator_id)

    assert the_list.analysis_state == RelatedAnalysisState.MATCHES_AVAILABLE
    assert [c.candidate_report_reference for c in the_list.candidates] == [the_candidate_ref]
    assert the_list.candidates[0].ownership_state == CandidateOwnershipState.UNCLAIMED
    assert {s.code for s in the_list.candidates[0].signals} == {"same_dive_site", "close_observation_time"}

    # AC5: Claim and Compare takes ownership and returns both sides
    the_comparison = await the_service.claim_and_compare(
        the_session, the_source_ref, the_candidate_ref, the_coordinator_id
    )

    assert the_comparison.candidate.report_reference == the_candidate_ref
    assert the_comparison.relatedness_level == RelatednessLevel.HIGH

    # AC7: Not Related is recorded and remembered
    await the_service.record_relationship_decision(
        the_session, the_source_ref, the_candidate_ref, the_coordinator_id,
        RelationshipDecisionCreate(decision="not_related", rejection_reason_code="different_object"),
    )

    the_list = await the_service.get_related_reports(the_session, the_source_ref, the_coordinator_id)
    assert the_list.candidates[0].decision_state == CandidateDecisionState.NOT_RELATED

    # AC6: a later Confirm Same Incident links both under one incident
    the_confirmed = await the_service.record_relationship_decision(
        the_session, the_source_ref, the_candidate_ref, the_coordinator_id,
        RelationshipDecisionCreate(decision="same_incident"),
    )

    assert the_confirmed.incident_reference.startswith("INC-")

    the_list = await the_service.get_related_reports(the_session, the_source_ref, the_coordinator_id)
    assert the_list.candidates[0].decision_state == CandidateDecisionState.LINKED

    # AC8: relatedness never moved either case
    assert await current_status(the_session, the_source_ref) == "claimed"
    assert await current_status(the_session, the_candidate_ref) == "claimed"

    # US1.3 AC2: another Coordinator's report cannot be compared
    if the_rows["other_owned"] is not None:
        with pytest.raises(AuthorizationError):
            await the_service.compare_reports(
                the_session, the_source_ref,
                the_rows["other_owned"]["report_reference"], the_coordinator_id,
            )

    # the database refuses a direct incident_id write (last: it aborts)
    with pytest.raises(DBAPIError):
        await the_session.execute(
            text("UPDATE report SET incident_id = NULL WHERE report_reference = :ref"),
            {"ref": the_source_ref},
        )
