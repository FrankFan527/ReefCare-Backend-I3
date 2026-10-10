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
# ---------------------------------------------------------------------------

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


INFORMATION_REQUEST_EVENT: str = "info_requested"
INFORMATION_RESPONSE_EVENT: str = "info_provided"

# The only status in which an information request is open. Once the observer
# answers, the case returns to under_review and the request is closed.
NEEDS_MORE_INFO_STATUS: str = "needs_more_info"


async def get_report_for_observer(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> dict | None:
    """
    Return a report only if this observer submitted it.

    Returns None both when the reference does not exist and when it belongs to
    somebody else, so the caller cannot use the difference to discover whether
    a report exists. The caller turns None into a 404 either way.

    claimed_by_user_id is returned because US6.3 AC3 requires the existing
    coordinator ownership to survive the response, and the only way to show
    that in a test is to read it before and after.
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
                ON cs.case_status_id = r.current_status_id

            WHERE
                r.report_reference = :report_reference
                AND r.observer_id = :observer_id
                AND r.deleted_at IS NULL
            """
        ),
        {
            "report_reference": report_reference,
            "observer_id": observer_id,
        },
    )

    the_report_row = (
        the_report_result
        .mappings()
        .first()
    )

    if the_report_row is None:
        return None

    return dict(the_report_row)


async def get_open_information_request(
    db: AsyncSession,
    report_reference: str,
) -> dict | None:
    """
    Return the information request the observer still needs to answer.

    Open means two things at once: the most recent info_requested event, and a
    case still sitting in needs_more_info. Checking only the event would keep
    showing an old request forever, because case_event is append-only and the
    request is never deleted once answered.

    Returns None when there is nothing to answer.
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
                ON r.report_id = e.report_id

            JOIN case_status AS cs
                ON cs.case_status_id = r.current_status_id

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL
                AND e.event_type = :request_event
                AND cs.code = :open_status

            ORDER BY e.case_event_id DESC

            LIMIT 1
            """
        ),
        {
            "report_reference": report_reference,
            "request_event": INFORMATION_REQUEST_EVENT,
            "open_status": NEEDS_MORE_INFO_STATUS,
        },
    )

    the_request_row = (
        the_request_result
        .mappings()
        .first()
    )

    if the_request_row is None:
        return None

    return dict(the_request_row)


async def list_information_exchange(
    db: AsyncSession,
    report_reference: str,
) -> list[dict]:
    """
    Return every request and response on one case, oldest first.

    This is what US6.3 AC4 means by displaying the new information clearly for
    re-review: the coordinator needs to see what was asked alongside what came
    back, not just the latest note.

    Ordered by case_event_id rather than occurred_at so two events written in
    the same transaction still read back in the order they happened, matching
    how reefcare_report_timeline() orders.
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
                u.display_name AS actor_display_name

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id = e.report_id

            LEFT JOIN app_user AS u
                ON u.user_id = e.actor_user_id

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL
                AND e.event_type IN (
                    :request_event,
                    :response_event
                )

            ORDER BY e.case_event_id ASC
            """
        ),
        {
            "report_reference": report_reference,
            "request_event": INFORMATION_REQUEST_EVENT,
            "response_event": INFORMATION_RESPONSE_EVENT,
        },
    )

    return [
        dict(the_row)
        for the_row in the_exchange_result.mappings().all()
    ]

async def get_latest_information_response_event_id(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
) -> int | None:
    """
    The info_provided event this observer has just written.

    reefcare_change_status() writes the event but returns only the new status
    code, so the photos of a reply find their event here. Called inside the
    same transaction straight after the status move, which holds the report
    in under_review, so a second reply cannot slip in between.
    """

    the_event_result = await db.execute(
        text(
            """
            SELECT MAX(e.case_event_id)

            FROM case_event AS e

            JOIN report AS r
                ON r.report_id = e.report_id

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL
                AND e.event_type = :response_event
                AND e.actor_user_id = :observer_id
            """
        ),
        {
            "report_reference": report_reference,
            "response_event": INFORMATION_RESPONSE_EVENT,
            "observer_id": observer_id,
        },
    )

    return the_event_result.scalar_one_or_none()


async def list_information_response_evidence(
    db: AsyncSession,
    report_reference: str,
) -> dict[int, list[dict]]:
    """
    Photos sent with observer replies, keyed by the info_provided event they
    arrived with, so the coordinator sees each photo beside the answer it
    came with (US6.3 AC4) rather than mixed in with the original submission.

    Safe metadata only: file_reference stays private, and the image streams
    through the existing owner-checked evidence route.
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
                ON ce.case_event_id = e.case_event_id

            JOIN report AS r
                ON r.report_id = e.report_id

            WHERE
                r.report_reference = :report_reference
                AND r.deleted_at IS NULL
                AND ce.event_type = :response_event

            ORDER BY e.case_event_id, e.display_order, e.evidence_id
            """
        ),
        {
            "report_reference": report_reference,
            "response_event": INFORMATION_RESPONSE_EVENT,
        },
    )

    the_evidence_by_event: dict[int, list[dict]] = {}

    for the_row in the_evidence_result.mappings().all():
        the_item = dict(the_row)
        the_event_id = the_item.pop("case_event_id")

        the_evidence_by_event.setdefault(the_event_id, []).append(the_item)

    return the_evidence_by_event
