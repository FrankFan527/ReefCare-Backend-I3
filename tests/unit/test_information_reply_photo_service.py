# ---------------------------------------------------------------------------
# US6.3 observer reply with photos — unit tests (no database).
#
# QA (Rifdhan, 10 Oct): a Coordinator asks for a wider photo, and the
# Observer could only answer in text. These pin the rules of the photo reply:
#
#   - only the submitting Observer, only while a question is open
#   - every file checked before anything is stored
#   - reply and photos saved together or not at all, no orphaned files
#   - photos linked to the reply's info_provided event
#   - the same Coordinator keeps the case
#
# Plus a regression check that the text-only reply still behaves as before
# after its checks moved into information_service.load_report_with_open_request().
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import ConflictError, NotFoundError, WorkflowError
from app.schemas.report import MAX_INFORMATION_RESPONSE_PHOTOS
from app.services import information_reply_photo_service as the_photo_service
from app.services import information_service as the_service
from app.services.evidence_service import EvidenceValidationError


THE_OPEN_REPORT: dict = {
    "report_reference": "RC-0101",
    "status_code": "needs_more_info",
    "claimed_by_user_id": 12,
}


def make_stored_file(the_number: int):
    return type(
        "the_stored_file", (), {
            "file_reference": f"evidence/private/reply-{the_number}.jpg",
            "file_size_bytes": 1000 + the_number,
        },
    )()


def make_reply_mocks(monkeypatch, the_report=THE_OPEN_REPORT):
    """
    Wire the reply to mocks and hand them back, so each test can check what
    was (and was not) stored, written or cleaned up.
    """

    the_stored_counter = {"n": 0}

    async def fake_store(photo, content):
        the_stored_counter["n"] += 1
        return make_stored_file(the_stored_counter["n"])

    the_evidence_counter = {"n": 500}

    async def fake_save_evidence(**the_kwargs):
        the_evidence_counter["n"] += 1
        return {
            "evidence_id": the_evidence_counter["n"],
            "media_type": "photo",
            "file_size_bytes": the_kwargs["file_size_bytes"],
            "uploaded_at": "2026-10-10T03:00:00+00:00",
        }

    the_mocks = {
        "get_report_for_observer": AsyncMock(return_value=the_report),
        "get_open_information_request": AsyncMock(
            return_value={"case_event_id": 880, "request_text": "Please upload a wider photo of the net."}
        ),
        "validate_photo": AsyncMock(return_value=b"\xff\xd8\xff-photo-bytes"),
        "store_private_evidence": AsyncMock(side_effect=fake_store),
        "change_status": AsyncMock(return_value="under_review"),
        "get_latest_information_response_event_id": AsyncMock(return_value=881),
        "save_action_evidence": AsyncMock(side_effect=fake_save_evidence),
        "delete_private_evidence": AsyncMock(),
    }

    # the ownership, request and status checks live in information_service;
    # files and the evidence link live in the photo reply module
    the_information_names = {"get_report_for_observer", "get_open_information_request", "change_status"}

    for the_name, the_mock in the_mocks.items():
        the_target = the_service if the_name in the_information_names else the_photo_service
        monkeypatch.setattr(the_target, the_name, the_mock)

    return the_mocks


async def send_reply(the_db, the_photo_count: int = 2, the_observer_id: int = 7):
    return await the_photo_service.respond_to_information_request_with_photos(
        db=the_db,
        report_reference="RC-0101",
        observer_id=the_observer_id,
        response_text="Wider photo attached, the net runs along the ledge.",
        photos=[object() for _ in range(the_photo_count)],
    )


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reply_and_photos_are_saved_together_on_the_reply_event(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)
    the_db = AsyncMock()

    the_result = await send_reply(the_db)

    # the reply moved the case the same way a text reply does
    the_status_move = the_mocks["change_status"].await_args.kwargs
    assert the_status_move["status_code"] == "under_review"
    assert the_status_move["event_type"] == "info_provided"
    assert the_status_move["actor_user_id"] == 7
    assert the_status_move["note"].startswith("Wider photo attached")

    # every photo hangs off the reply's event and records the Observer
    for the_call in the_mocks["save_action_evidence"].await_args_list:
        assert the_call.kwargs["case_event_id"] == 881
        assert the_call.kwargs["uploaded_by_user_id"] == 7

    assert the_mocks["save_action_evidence"].await_count == 2
    the_db.commit.assert_awaited_once()
    the_mocks["delete_private_evidence"].assert_not_awaited()

    assert the_result["case_event_id"] == 881
    assert [the_item["evidence_id"] for the_item in the_result["evidence"]] == [501, 502]
    # US6.3 AC3: the same coordinator still owns the case
    assert the_result["coordinator_retained"] == 12
    # the private storage key never leaves the backend
    assert all("file_reference" not in the_item for the_item in the_result["evidence"])


@pytest.mark.asyncio
async def test_a_reply_without_photos_is_still_a_valid_reply(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)
    the_db = AsyncMock()

    the_result = await send_reply(the_db, the_photo_count=0)

    the_mocks["store_private_evidence"].assert_not_awaited()
    the_mocks["change_status"].assert_awaited_once()
    the_db.commit.assert_awaited_once()
    assert the_result["evidence"] == []


# ---------------------------------------------------------------------------
# refusals happen before anything is stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_another_observers_report_is_not_found_and_reads_no_files(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch, the_report=None)

    with pytest.raises(NotFoundError):
        await send_reply(AsyncMock(), the_observer_id=99)

    the_mocks["validate_photo"].assert_not_awaited()
    the_mocks["store_private_evidence"].assert_not_awaited()


@pytest.mark.asyncio
async def test_no_open_question_means_no_reply(monkeypatch):
    the_mocks = make_reply_mocks(
        monkeypatch, the_report={**THE_OPEN_REPORT, "status_code": "under_review"}
    )

    with pytest.raises(WorkflowError):
        await send_reply(AsyncMock())

    the_mocks["store_private_evidence"].assert_not_awaited()
    the_mocks["change_status"].assert_not_awaited()


@pytest.mark.asyncio
async def test_too_many_photos_are_refused(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)

    with pytest.raises(EvidenceValidationError):
        await send_reply(AsyncMock(), the_photo_count=MAX_INFORMATION_RESPONSE_PHOTOS + 1)

    the_mocks["store_private_evidence"].assert_not_awaited()


@pytest.mark.asyncio
async def test_one_bad_photo_stores_none_of_them(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)
    the_mocks["validate_photo"].side_effect = [
        b"\xff\xd8\xff-good",
        EvidenceValidationError("Unsupported photo type. Allowed types are JPEG, PNG and WebP."),
    ]

    with pytest.raises(EvidenceValidationError):
        await send_reply(AsyncMock())

    the_mocks["store_private_evidence"].assert_not_awaited()
    the_mocks["change_status"].assert_not_awaited()


# ---------------------------------------------------------------------------
# all or nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_failed_photo_insert_rolls_back_and_removes_every_file(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)
    the_mocks["save_action_evidence"].side_effect = DBAPIError("INSERT", {}, Exception("boom"))
    the_db = AsyncMock()

    with pytest.raises(ConflictError):
        await send_reply(the_db)

    the_db.rollback.assert_awaited()
    the_db.commit.assert_not_awaited()
    assert sorted(
        the_call.args[0] for the_call in the_mocks["delete_private_evidence"].await_args_list
    ) == ["evidence/private/reply-1.jpg", "evidence/private/reply-2.jpg"]


@pytest.mark.asyncio
async def test_a_racing_second_reply_is_a_conflict_with_no_files_left(monkeypatch):
    # the case already moved to under_review: reefcare_change_status refuses
    the_mocks = make_reply_mocks(monkeypatch)
    the_mocks["change_status"].side_effect = DBAPIError("SELECT", {}, Exception("transition"))
    the_db = AsyncMock()

    with pytest.raises(ConflictError):
        await send_reply(the_db)

    the_db.rollback.assert_awaited()
    assert the_mocks["delete_private_evidence"].await_count == 2
    the_mocks["save_action_evidence"].assert_not_awaited()


# ---------------------------------------------------------------------------
# regression: the text-only reply after the refactor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_text_reply_still_moves_the_case_and_keeps_the_coordinator(monkeypatch):
    make_reply_mocks(monkeypatch)
    the_db = AsyncMock()

    the_result = await the_service.respond_to_information_request(
        db=the_db,
        report_reference="RC-0101",
        observer_id=7,
        response_text="It was a gill net.",
    )

    assert the_result == {
        "report_reference": "RC-0101",
        "status": "under_review",
        "response_text": "It was a gill net.",
        "coordinator_retained": 12,
    }
    # the text reply still leaves the commit to its route
    the_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_reply_refused_when_nothing_was_asked(monkeypatch):
    the_mocks = make_reply_mocks(monkeypatch)
    the_mocks["get_open_information_request"].return_value = None

    with pytest.raises(WorkflowError):
        await the_service.respond_to_information_request(
            db=AsyncMock(),
            report_reference="RC-0101",
            observer_id=7,
            response_text="Answer to nothing",
        )

    the_mocks["change_status"].assert_not_awaited()


# ---------------------------------------------------------------------------
# the coordinator sees each reply with its photos
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_attaches_photos_to_the_reply_they_came_with(monkeypatch):
    monkeypatch.setattr(
        the_service, "list_information_exchange",
        AsyncMock(return_value=[
            {"case_event_id": 880, "event_type": "info_requested", "message": "Wider photo please"},
            {"case_event_id": 881, "event_type": "info_provided", "message": "Attached"},
        ]),
    )
    monkeypatch.setattr(
        the_service, "list_information_response_evidence",
        AsyncMock(return_value={881: [{"evidence_id": 501, "media_type": "photo"}]}),
    )

    the_exchange = await the_service.get_information_exchange(AsyncMock(), "RC-0101")

    assert the_exchange[0]["evidence"] == []
    assert the_exchange[1]["evidence"] == [{"evidence_id": 501, "media_type": "photo"}]
