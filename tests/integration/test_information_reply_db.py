# ---------------------------------------------------------------------------
# US6.3 observer reply with photos — integration test against a real database.
#
# Run like test_follow_up_db.py, with DATABASE_URL on a dev branch and never
# production. Everything runs inside one outer transaction that is rolled
# back. No file is stored: the evidence rows point at a placeholder key, so
# this checks the database side of the reply (the event link, the retained
# coordinator and the coordinator's view), not Supabase.
# ---------------------------------------------------------------------------

import pytest
from sqlalchemy import text

from app.repositories.case_action_repository import save_action_evidence
from app.repositories.information_repository import (
    get_latest_information_response_event_id,
)
from app.services import information_service as the_service

# the same rolled-back session, production guard included
from tests.integration.test_follow_up_db import the_session  # noqa: F401


pytestmark = pytest.mark.integration


async def find_report_awaiting_an_answer(the_db) -> dict | None:
    """
    A live report in needs_more_info whose latest request is on record.
    """

    the_row = (
        await the_db.execute(text(
            """
            SELECT r.report_reference, r.observer_id, r.claimed_by_user_id
            FROM report AS r
            JOIN case_status AS cs ON cs.case_status_id = r.current_status_id
            WHERE cs.code = 'needs_more_info'
              AND r.deleted_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM case_event AS e
                  WHERE e.report_id = r.report_id
                    AND e.event_type = 'info_requested'
              )
            ORDER BY r.report_id
            LIMIT 1
            """
        ))
    ).mappings().first()

    return dict(the_row) if the_row else None


@pytest.mark.asyncio
async def test_reply_photo_links_to_the_reply_and_keeps_the_coordinator(the_session):  # noqa: F811
    the_report = await find_report_awaiting_an_answer(the_session)

    if the_report is None:
        pytest.skip("No needs_more_info report with a recorded request on this database")

    the_reference = the_report["report_reference"]
    the_observer_id = the_report["observer_id"]

    # the same status move the photo reply makes before linking its photos
    the_result = await the_service.respond_to_information_request(
        db=the_session,
        report_reference=the_reference,
        observer_id=the_observer_id,
        response_text="Wider photo attached (integration test)",
    )

    assert the_result["status"] == "under_review"

    the_event_id = await get_latest_information_response_event_id(
        db=the_session,
        report_reference=the_reference,
        observer_id=the_observer_id,
    )

    assert the_event_id is not None

    the_photo = await save_action_evidence(
        db=the_session,
        report_reference=the_reference,
        case_event_id=the_event_id,
        uploaded_by_user_id=the_observer_id,
        file_reference="integration-test/not-a-real-file.jpg",
        file_size_bytes=1234,
    )

    # US6.3 AC3: the same coordinator still owns the case
    the_owner_after = (
        await the_session.execute(
            text("SELECT claimed_by_user_id FROM report WHERE report_reference = :ref"),
            {"ref": the_reference},
        )
    ).scalar_one()

    assert the_owner_after == the_report["claimed_by_user_id"]

    # US6.3 AC4: the coordinator sees the photo beside the answer it came with
    the_exchange = await the_service.get_information_exchange(the_session, the_reference)
    the_reply = next(
        the_entry for the_entry in the_exchange
        if the_entry["case_event_id"] == the_event_id
    )

    assert the_reply["event_type"] == "info_provided"
    assert [the_item["evidence_id"] for the_item in the_reply["evidence"]] == [
        the_photo["evidence_id"]
    ]

    # the related-incident engine counts reply photos as report evidence
    the_counted = (
        await the_session.execute(
            text(
                """
                SELECT count(*) FROM evidence AS e
                LEFT JOIN case_event AS ce ON ce.case_event_id = e.case_event_id
                WHERE e.evidence_id = :id
                  AND (e.case_event_id IS NULL OR ce.event_type = 'info_provided')
                """
            ),
            {"id": the_photo["evidence_id"]},
        )
    ).scalar_one()

    assert the_counted == 1
