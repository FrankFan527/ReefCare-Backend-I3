# ---------------------------------------------------------------------------
# Information request and response persistence (US5.3, US6.3).
#
# There is no information_request table, and Iteration 2 does not add one.
# case_event already carries event_type, actor_user_id, occurred_at and note,
# which is every field US6.3 AC5 asks to be traceable. A separate table would
# duplicate all four and introduce a second place where the case history could
# disagree with itself.
#
# The exchange is therefore a projection over case_event:
#
#   info_requested   the coordinator asking, note carries the request
#   info_provided    the observer answering, note carries the response
#
# Both event types are already permitted by case_event_type_valid.
#
# Iteration 3 / E6 extends the existing response flow with private evidence
# photos. Those photos remain rows in the existing evidence table and are
# linked to the specific info_provided case_event through evidence.case_event_id.
#
# No new database table is required.
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


INFORMATION_REQUEST_EVENT: str = "info_requested"
INFORMATION_RESPONSE_EVENT: str = "info_provided"

# The only status in which an information request is open.
#
# Once the Observer answers, the case returns to under_review and the request
# is no longer open.
NEEDS_MORE_INFO_STATUS: str = "needs_more_info"


async def get_report_for_observer(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> dict | None:
    """
    Return a report only if this Observer submitted it.

    Returns None both when the reference does not exist and
    when it belongs to somebody else.

    This prevents report-reference enumeration.

    claimed_by_user_id is returned because US6.3 requires
    the same Coordinator to retain ownership after the
    Observer supplies additional information.
    """

    the_report_result = await db.execute(
        text(
            """
            SELECT
                r.report_id,
                r.report_reference,
                r.observer_id,
                r.claimed_by_user_id,

                cs.code AS status_code,
                cs.observer_label AS status_label

            FROM report AS r

            JOIN case_status AS cs
                ON cs.case_status_id =
                    r.current_status_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at
                    IS NULL

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "observer_id":
                observer_id,
        },
    )

    the_report_row = (
        the_report_result
        .mappings()
        .first()
    )

    if the_report_row is None:
        return None

    return dict(
        the_report_row
    )


async def get_open_information_request(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Return the information request the Observer still needs
    to answer.

    Open means two things at once:

    1. an info_requested event exists
    2. the case is still in needs_more_info

    Checking only case_event would cause an old request to
    remain visible forever because case_event is append-only.

    Returns None when there is currently nothing to answer.
    """

    the_request_result = await db.execute(
        text(
            """
            SELECT
                e.case_event_id,

                e.note AS request_text,

                e.occurred_at AS requested_at,

                e.actor_user_id AS requested_by

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id =
                    e.report_id

            JOIN case_status AS cs
                ON cs.case_status_id =
                    r.current_status_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

                AND e.event_type =
                    :request_event

                AND cs.code =
                    :open_status

            ORDER BY
                e.occurred_at DESC,
                e.case_event_id DESC

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "request_event":
                INFORMATION_REQUEST_EVENT,

            "open_status":
                NEEDS_MORE_INFO_STATUS,
        },
    )

    the_request_row = (
        the_request_result
        .mappings()
        .first()
    )

    if the_request_row is None:
        return None

    return dict(
        the_request_row
    )


async def list_information_exchange(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return every request and response on one case,
    oldest first.

    This allows the Coordinator to re-review the case while
    seeing what was requested beside the Observer's reply.

    case_event_id is retained because response evidence is
    grouped by the info_provided event that created it.
    """

    the_exchange_result = await db.execute(
        text(
            """
            SELECT
                e.case_event_id,
                e.event_type,

                e.note AS message,

                e.occurred_at,
                e.actor_user_id,

                u.display_name
                    AS actor_display_name

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id =
                    e.report_id

            LEFT JOIN app_user AS u
                ON u.user_id =
                    e.actor_user_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

                AND e.event_type IN (
                    :request_event,
                    :response_event
                )

            ORDER BY
                e.occurred_at ASC,
                e.case_event_id ASC
            """
        ),
        {
            "report_reference":
                report_reference,

            "request_event":
                INFORMATION_REQUEST_EVENT,

            "response_event":
                INFORMATION_RESPONSE_EVENT,
        },
    )

    return [
        dict(
            the_row
        )
        for the_row
        in (
            the_exchange_result
            .mappings()
            .all()
        )
    ]


async def get_latest_information_response_event_id(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> int | None:
    """
    Return the newest info_provided event written by this
    Observer for this Observer-owned report.

    reefcare_change_status() creates the case_event but
    returns only the new status code.

    The photo-reply service therefore resolves the newly
    created info_provided event immediately afterwards,
    inside the same database transaction.

    The query deliberately verifies:

    - report reference
    - report ownership
    - live report
    - info_provided event type
    - Observer event actor

    This prevents an evidence item from being linked to
    another report or another user's event.
    """

    the_event_result = await db.execute(
        text(
            """
            SELECT
                e.case_event_id

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id =
                    e.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at
                    IS NULL

                AND e.event_type =
                    :response_event

                AND e.actor_user_id =
                    :observer_id

            ORDER BY
                e.occurred_at DESC,
                e.case_event_id DESC

            LIMIT 1
            """
        ),
        {
            "report_reference":
                report_reference,

            "observer_id":
                observer_id,

            "response_event":
                INFORMATION_RESPONSE_EVENT,
        },
    )

    return (
        the_event_result
        .scalar_one_or_none()
    )


async def save_information_response_evidence(
    db: AsyncSession,
    *,
    report_reference: str,
    case_event_id: int,
    observer_id: int,
    file_reference: str,
    file_size_bytes: int,
) -> dict | None:
    """
    Persist one private photo belonging to an Observer's
    info_provided response event.

    Security and integrity conditions are checked again in
    the INSERT query rather than relying only on the service
    layer:

    - the report must exist and not be deleted
    - the report must belong to this Observer
    - the case_event must belong to the same report
    - the case_event must be info_provided
    - the case_event actor must be this Observer

    file_reference remains private and is deliberately not
    included in RETURNING.

    The caller owns the transaction and commit.
    """

    the_result = await db.execute(
        text(
            """
            INSERT INTO evidence
                (
                    report_id,
                    dive_session_id,
                    media_type,
                    file_reference,
                    file_size_bytes,
                    display_order,
                    case_event_id,
                    uploaded_by_user_id
                )

            SELECT
                r.report_id,

                r.dive_session_id,

                'photo',

                :file_reference,

                :file_size_bytes,

                COALESCE(
                    (
                        SELECT
                            MAX(
                                e2.display_order
                            ) + 1

                        FROM evidence AS e2

                        WHERE
                            e2.report_id =
                                r.report_id
                    ),
                    0
                ),

                ce.case_event_id,

                :observer_id

            FROM report AS r

            JOIN case_event AS ce
                ON ce.report_id =
                    r.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.observer_id =
                    :observer_id

                AND r.deleted_at
                    IS NULL

                AND ce.case_event_id =
                    :case_event_id

                AND ce.event_type =
                    :response_event

                AND ce.actor_user_id =
                    :observer_id

            RETURNING
                evidence_id,
                media_type,
                file_size_bytes,
                uploaded_at
            """
        ),
        {
            "report_reference":
                report_reference,

            "case_event_id":
                case_event_id,

            "observer_id":
                observer_id,

            "file_reference":
                file_reference,

            "file_size_bytes":
                file_size_bytes,

            "response_event":
                INFORMATION_RESPONSE_EVENT,
        },
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


async def list_information_response_evidence(
    db: AsyncSession,
    report_reference: str,
) -> dict[int, list[dict]]:
    """
    Return photos sent with Observer information replies,
    grouped by their info_provided case_event.

    This allows the Coordinator case projection to show
    each photo beside the reply it belongs to instead of
    mixing these images with the original report evidence.

    Only safe metadata is returned.

    file_reference remains private and must be accessed
    through the existing protected evidence route.
    """

    the_evidence_result = await db.execute(
        text(
            """
            SELECT
                e.case_event_id,
                e.evidence_id,
                e.media_type,
                e.file_size_bytes,
                e.uploaded_at

            FROM evidence AS e

            JOIN case_event AS ce
                ON ce.case_event_id =
                    e.case_event_id

                AND ce.report_id =
                    e.report_id

            JOIN report AS r
                ON r.report_id =
                    e.report_id

            WHERE
                r.report_reference =
                    :report_reference

                AND r.deleted_at
                    IS NULL

                AND ce.event_type =
                    :response_event

            ORDER BY
                e.case_event_id,
                e.display_order,
                e.evidence_id
            """
        ),
        {
            "report_reference":
                report_reference,

            "response_event":
                INFORMATION_RESPONSE_EVENT,
        },
    )

    the_evidence_by_event: dict[
        int,
        list[dict],
    ] = {}

    for the_row in (
        the_evidence_result
        .mappings()
        .all()
    ):
        the_item = dict(
            the_row
        )

        the_event_id = (
            the_item.pop(
                "case_event_id"
            )
        )

        (
            the_evidence_by_event
            .setdefault(
                the_event_id,
                [],
            )
            .append(
                the_item
            )
        )

    return (
        the_evidence_by_event
    )