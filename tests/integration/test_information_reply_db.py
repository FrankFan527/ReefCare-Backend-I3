# ---------------------------------------------------------------------------
# US6.3 observer reply with photos — real database integration test.
#
# Run only against a development/QA database branch.
#
# Everything is executed through the rolled-back integration session,
# so no permanent report/status/evidence change remains.
#
# No Supabase object is stored here. The evidence metadata points at a
# placeholder private object key.
#
# This test verifies:
#
# - needs_more_info -> under_review
# - info_provided case event is created
# - reply photo links to that exact event
# - Observer ownership is enforced by the repository
# - same Coordinator remains assigned
# - Coordinator information exchange sees the photo beside the reply
# ---------------------------------------------------------------------------

import pytest

from sqlalchemy import text

from app.repositories.information_repository import (
    get_latest_information_response_event_id,
    save_information_response_evidence,
)
from app.services import (
    information_service as the_service,
)

# Reuse the same production-guarded, rolled-back session
# fixture used by the E7 database tests.
from tests.integration.test_follow_up_db import (
    the_session,
)  # noqa: F401


pytestmark = pytest.mark.integration


async def find_report_awaiting_an_answer(
    the_db,
) -> dict | None:
    """
    Find one live Observer-owned report currently in
    needs_more_info with an info_requested event.
    """

    the_result = await the_db.execute(
        text(
            """
            SELECT
                r.report_reference,
                r.observer_id,
                r.claimed_by_user_id

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                    r.current_status_id

            WHERE
                cs.code =
                    'needs_more_info'

                AND r.deleted_at
                    IS NULL

                AND EXISTS (
                    SELECT
                        1

                    FROM case_event AS e

                    WHERE
                        e.report_id =
                            r.report_id

                        AND e.event_type =
                            'info_requested'
                )

            ORDER BY
                r.report_id

            LIMIT 1
            """
        )
    )

    the_row = (
        the_result
        .mappings()
        .first()
    )

    if the_row is None:
        return None

    return dict(
        the_row
    )


@pytest.mark.asyncio
async def test_reply_photo_links_to_the_reply_and_keeps_the_coordinator(
    the_session,
):  # noqa: F811
    the_report = (
        await find_report_awaiting_an_answer(
            the_session
        )
    )

    if the_report is None:
        pytest.skip(
            "No needs_more_info report with "
            "a recorded request exists on "
            "this database"
        )

    the_reference = (
        the_report[
            "report_reference"
        ]
    )

    the_observer_id = (
        the_report[
            "observer_id"
        ]
    )

    the_original_coordinator = (
        the_report[
            "claimed_by_user_id"
        ]
    )

    # --------------------------------------------------------------
    # Perform the canonical Observer response workflow.
    #
    # This creates the info_provided event and returns
    # the report to under_review.
    # --------------------------------------------------------------

    the_result = (
        await (
            the_service
            .respond_to_information_request(
                db=the_session,

                report_reference=(
                    the_reference
                ),

                observer_id=(
                    the_observer_id
                ),

                response_text=(
                    "Wider photo attached "
                    "(integration test)"
                ),
            )
        )
    )

    assert (
        the_result[
            "status"
        ]
        == "under_review"
    )

    assert (
        the_result[
            "coordinator_retained"
        ]
        == the_original_coordinator
    )

    # --------------------------------------------------------------
    # Resolve the newly-created info_provided case event.
    # --------------------------------------------------------------

    the_event_id = (
        await (
            get_latest_information_response_event_id(
                db=the_session,

                report_reference=(
                    the_reference
                ),

                observer_id=(
                    the_observer_id
                ),
            )
        )
    )

    assert (
        the_event_id
        is not None
    )

    # --------------------------------------------------------------
    # Confirm that the event belongs to this Observer/report.
    # --------------------------------------------------------------

    the_event_result = (
        await the_session.execute(
            text(
                """
                SELECT
                    ce.case_event_id,
                    ce.event_type,
                    ce.actor_user_id,
                    ce.note

                FROM case_event AS ce

                JOIN report AS r
                    ON r.report_id =
                        ce.report_id

                WHERE
                    ce.case_event_id =
                        :case_event_id

                    AND r.report_reference =
                        :report_reference
                """
            ),
            {
                "case_event_id":
                    the_event_id,

                "report_reference":
                    the_reference,
            },
        )
    )

    the_event = (
        the_event_result
        .mappings()
        .one()
    )

    assert (
        the_event[
            "event_type"
        ]
        == "info_provided"
    )

    assert (
        the_event[
            "actor_user_id"
        ]
        == the_observer_id
    )

    # --------------------------------------------------------------
    # Persist one reply photo through the E6 repository.
    #
    # E6 deliberately does not depend on E7's
    # case_action_repository.
    # --------------------------------------------------------------

    the_photo = (
        await (
            save_information_response_evidence(
                db=the_session,

                report_reference=(
                    the_reference
                ),

                case_event_id=(
                    the_event_id
                ),

                observer_id=(
                    the_observer_id
                ),

                file_reference=(
                    "integration-test/"
                    "not-a-real-file.jpg"
                ),

                file_size_bytes=(
                    1234
                ),
            )
        )
    )

    assert (
        the_photo
        is not None
    )

    assert (
        the_photo[
            "media_type"
        ]
        == "photo"
    )

    assert (
        the_photo[
            "file_size_bytes"
        ]
        == 1234
    )

    # --------------------------------------------------------------
    # US6.3 AC3:
    # same Coordinator remains assigned after reply.
    # --------------------------------------------------------------

    the_owner_result = (
        await the_session.execute(
            text(
                """
                SELECT
                    claimed_by_user_id

                FROM report

                WHERE
                    report_reference =
                        :report_reference
                """
            ),
            {
                "report_reference":
                    the_reference,
            },
        )
    )

    the_owner_after = (
        the_owner_result
        .scalar_one()
    )

    assert (
        the_owner_after
        == the_original_coordinator
    )

    # --------------------------------------------------------------
    # Verify the evidence row itself is linked correctly.
    # --------------------------------------------------------------

    the_evidence_result = (
        await the_session.execute(
            text(
                """
                SELECT
                    e.evidence_id,
                    e.report_id,
                    e.case_event_id,
                    e.uploaded_by_user_id,
                    e.media_type,
                    e.file_reference

                FROM evidence AS e

                WHERE
                    e.evidence_id =
                        :evidence_id
                """
            ),
            {
                "evidence_id":
                    the_photo[
                        "evidence_id"
                    ],
            },
        )
    )

    the_saved_evidence = (
        the_evidence_result
        .mappings()
        .one()
    )

    assert (
        the_saved_evidence[
            "case_event_id"
        ]
        == the_event_id
    )

    assert (
        the_saved_evidence[
            "uploaded_by_user_id"
        ]
        == the_observer_id
    )

    assert (
        the_saved_evidence[
            "media_type"
        ]
        == "photo"
    )

    # --------------------------------------------------------------
    # US6.3 AC4:
    # Coordinator re-review sees the photo beside its reply.
    # --------------------------------------------------------------

    the_exchange = (
        await (
            the_service
            .get_information_exchange(
                the_session,
                the_reference,
            )
        )
    )

    the_reply = next(
        the_entry
        for the_entry
        in the_exchange
        if (
            the_entry[
                "case_event_id"
            ]
            == the_event_id
        )
    )

    assert (
        the_reply[
            "event_type"
        ]
        == "info_provided"
    )

    assert [
        the_item[
            "evidence_id"
        ]
        for the_item
        in the_reply[
            "evidence"
        ]
    ] == [
        the_photo[
            "evidence_id"
        ]
    ]

    # file_reference must never be part of the safe
    # Coordinator exchange projection.
    assert all(
        "file_reference"
        not in the_item
        for the_item
        in the_reply[
            "evidence"
        ]
    )

    # --------------------------------------------------------------
    # Related-incident eligibility:
    #
    # reply evidence counts as report evidence because it is
    # attached to an info_provided event.
    # --------------------------------------------------------------

    the_count_result = (
        await the_session.execute(
            text(
                """
                SELECT
                    COUNT(*)

                FROM evidence AS e

                LEFT JOIN case_event AS ce
                    ON ce.case_event_id =
                        e.case_event_id

                WHERE
                    e.evidence_id =
                        :evidence_id

                    AND (
                        e.case_event_id
                            IS NULL

                        OR ce.event_type =
                            'info_provided'
                    )
                """
            ),
            {
                "evidence_id":
                    the_photo[
                        "evidence_id"
                    ],
            },
        )
    )

    the_counted = (
        the_count_result
        .scalar_one()
    )

    assert (
        the_counted
        == 1
    )