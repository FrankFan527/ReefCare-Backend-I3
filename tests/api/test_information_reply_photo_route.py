# ---------------------------------------------------------------------------
# US6.3 observer reply with photos — route tests.
#
# multipart/form-data:
#
# responseText
# photos
#
# Success:
# - 201
# - reply data
# - safe evidence metadata
#
# Errors:
# - 400 invalid evidence
# - 409 invalid workflow state
# - 413 evidence too large
# - 422 missing/blank response text
#
# Related-incident detection is queued only when new photos
# were supplied.
# ---------------------------------------------------------------------------

from datetime import (
    datetime,
    timezone,
)
from unittest.mock import (
    AsyncMock,
)

import pytest

from fastapi.testclient import (
    TestClient,
)

from app.api.dependencies.authorization import (
    require_observer,
)
from app.api.routes import (
    reports as report_routes,
)
from app.core.exceptions import (
    WorkflowError,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.services.evidence_service import (
    EvidenceTooLargeError,
    EvidenceValidationError,
)


THE_REPLY_PATH: str = (
    "/api/v1/reports/"
    "RC-0101/"
    "information-response/"
    "with-photos"
)

THE_PHOTO = (
    "wider.jpg",
    b"\xff\xd8\xff-photo-bytes",
    "image/jpeg",
)


async def override_db_session():
    yield object()


def override_observer():
    return {
        "user_id": 7,
        "role": "observer",
    }


@pytest.fixture(
    autouse=True
)
def clean_dependency_overrides():
    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


@pytest.fixture
def the_client(
    monkeypatch,
):
    app.dependency_overrides[
        get_db_session
    ] = override_db_session

    app.dependency_overrides[
        require_observer
    ] = override_observer

    # Never run the real background detection task in a
    # route test.
    monkeypatch.setattr(
        report_routes,

        (
            "run_related_incident_"
            "detection_in_background"
        ),

        AsyncMock(),
    )

    with TestClient(
        app
    ) as the_test_client:
        yield the_test_client


def make_service_result(
    the_evidence: list[
        dict
    ],
) -> dict:
    return {
        "report_reference":
            "RC-0101",

        "status":
            "under_review",

        "response_text":
            "Wider photo attached",

        "coordinator_retained":
            12,

        "case_event_id":
            881,

        "evidence":
            the_evidence,
    }


def test_reply_with_photos_returns_the_reply_and_safe_photo_metadata(
    the_client,
    monkeypatch,
):
    the_service_mock = AsyncMock(
        return_value=(
            make_service_result(
                [
                    {
                        "evidence_id":
                            501,

                        "media_type":
                            "photo",

                        "file_size_bytes":
                            2048,

                        "uploaded_at":
                            datetime(
                                2026,
                                10,
                                10,
                                3,
                                0,
                                tzinfo=timezone.utc,
                            ),
                    }
                ]
            )
        )
    )

    monkeypatch.setattr(
        report_routes,

        (
            "respond_to_information_"
            "request_with_photos"
        ),

        the_service_mock,
    )

    the_response = (
        the_client.post(
            THE_REPLY_PATH,

            data={
                "responseText":
                    "  Wider photo attached  ",
            },

            files=[
                (
                    "photos",
                    THE_PHOTO,
                ),
                (
                    "photos",
                    THE_PHOTO,
                ),
            ],
        )
    )

    assert (
        the_response.status_code
        == 201
    )

    the_body = (
        the_response.json()
    )

    assert (
        the_body[
            "reportReference"
        ]
        == "RC-0101"
    )

    assert (
        the_body[
            "status"
        ]
        == "under_review"
    )

    assert (
        the_body[
            "coordinatorRetained"
        ]
        == 12
    )

    assert (
        the_body[
            "caseEventId"
        ]
        == 881
    )

    assert (
        the_body[
            "evidence"
        ]
        == [
            {
                "evidenceId":
                    501,

                "mediaType":
                    "photo",

                "fileSizeBytes":
                    2048,

                "uploadedAt":
                    "2026-10-10T03:00:00Z",
            }
        ]
    )

    # Private storage object key is never exposed.
    assert (
        "fileReference"
        not in (
            the_body[
                "evidence"
            ][0]
        )
    )

    the_kwargs = (
        the_service_mock
        .await_args
        .kwargs
    )

    assert (
        the_kwargs[
            "observer_id"
        ]
        == 7
    )

    assert (
        the_kwargs[
            "report_reference"
        ]
        == "RC-0101"
    )

    assert (
        len(
            the_kwargs[
                "photos"
            ]
        )
        == 2
    )

    assert (
        the_kwargs[
            "response_text"
        ]
        == (
            "  Wider photo "
            "attached  "
        )
    )

    # New photo evidence becomes new related-incident
    # detection input.
    (
        report_routes
        .run_related_incident_detection_in_background
        .assert_called_once_with(
            "RC-0101"
        )
    )


def test_text_only_multipart_reply_does_not_start_detection(
    the_client,
    monkeypatch,
):
    monkeypatch.setattr(
        report_routes,

        (
            "respond_to_information_"
            "request_with_photos"
        ),

        AsyncMock(
            return_value=(
                make_service_result(
                    []
                )
            )
        ),
    )

    the_response = (
        the_client.post(
            THE_REPLY_PATH,

            data={
                "responseText":
                    (
                        "No better photo, "
                        "sorry"
                    ),
            },
        )
    )

    assert (
        the_response.status_code
        == 201
    )

    assert (
        the_response.json()[
            "evidence"
        ]
        == []
    )

    (
        report_routes
        .run_related_incident_detection_in_background
        .assert_not_called()
    )


def test_blank_answer_is_refused_before_the_service(
    the_client,
    monkeypatch,
):
    the_service_mock = (
        AsyncMock()
    )

    monkeypatch.setattr(
        report_routes,

        (
            "respond_to_information_"
            "request_with_photos"
        ),

        the_service_mock,
    )

    the_response = (
        the_client.post(
            THE_REPLY_PATH,

            data={
                "responseText":
                    "   ",
            },

            files=[
                (
                    "photos",
                    THE_PHOTO,
                )
            ],
        )
    )

    assert (
        the_response.status_code
        == 422
    )

    the_service_mock.assert_not_awaited()


def test_missing_answer_is_refused(
    the_client,
):
    the_response = (
        the_client.post(
            THE_REPLY_PATH,

            files=[
                (
                    "photos",
                    THE_PHOTO,
                )
            ],
        )
    )

    assert (
        the_response.status_code
        == 422
    )


@pytest.mark.parametrize(
    (
        "the_error",
        "the_expected_status",
    ),
    [
        (
            EvidenceValidationError(
                "A reply can include "
                "at most 5 photos"
            ),
            400,
        ),
        (
            EvidenceTooLargeError(
                "Photo exceeds the "
                "maximum allowed size "
                "of 10 MB"
            ),
            413,
        ),
        (
            WorkflowError(
                "There is no open "
                "information request "
                "on this report"
            ),
            409,
        ),
    ],
)
def test_refusals_map_to_clear_statuses(
    the_client,
    monkeypatch,
    the_error,
    the_expected_status,
):
    monkeypatch.setattr(
        report_routes,

        (
            "respond_to_information_"
            "request_with_photos"
        ),

        AsyncMock(
            side_effect=(
                the_error
            )
        ),
    )

    the_response = (
        the_client.post(
            THE_REPLY_PATH,

            data={
                "responseText":
                    "Here it is",
            },

            files=[
                (
                    "photos",
                    THE_PHOTO,
                )
            ],
        )
    )

    assert (
        the_response.status_code
        == the_expected_status
    )

    assert (
        the_response.json()[
            "detail"
        ]
        == str(
            the_error
        )
    )

    (
        report_routes
        .run_related_incident_detection_in_background
        .assert_not_called()
    )


def test_a_coordinator_cannot_send_an_observer_reply():
    # No Observer override:
    # the real role dependency must reject the request.
    app.dependency_overrides[
        get_db_session
    ] = override_db_session

    with TestClient(
        app
    ) as the_test_client:

        the_response = (
            the_test_client.post(
                THE_REPLY_PATH,

                data={
                    "responseText":
                        "x",
                },

                files=[
                    (
                        "photos",
                        THE_PHOTO,
                    )
                ],
            )
        )

    assert (
        the_response.status_code
        in (
            401,
            403,
        )
    )