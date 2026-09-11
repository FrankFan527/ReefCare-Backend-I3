# ---------------------------------------------------------------------------
# Observer report tracking (US6.1 / US6.2).
#
# This service owns the Observer-facing projection and validation rules.
#
# The database remains the ownership boundary:
#   reefcare_my_reports(observer_id)
#   reefcare_report_timeline(report_reference, observer_id)
#   reefcare_report_location(report_reference, user_id)
#
# This layer deliberately does not expose coordinator identity, internal
# decision vocabulary or private evidence storage references.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy.exc import (
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.enums import (
    CaseStatus,
)
from app.core.exceptions import (
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories import (
    report_repository,
)
from app.repositories.location_repository import (
    get_report_location,
)
from app.schemas.report import (
    ObserverClosureSummary,
    ObserverLocationResponse,
    ObserverReportDetailResponse,
    ObserverReportListResponse,
    ObserverReportSummary,
    ObserverTimelineEvent,
    ObserverTimelineResponse,
)


class ObserverReportValidationError(
    ValueError
):
    """
    Raised when My Reports filter input is internally
    inconsistent.
    """


# These statuses already communicate an Observer-safe outcome before terminal
# closure. The text shown to the Observer comes from case_status.observer_label
# rather than from raw case_decision.response_type.
OPEN_DECISION_STATUSES: set[str] = {
    CaseStatus.MONITORING.value,
    CaseStatus.REFERRED.value,
    CaseStatus.RESPONSE_RECOMMENDED.value,
}


def observer_needs_attention(
    current_status,
) -> bool:
    """
    Whether the Observer currently has something to do.

    In the current workflow the only report state that
    requires Observer action is needs_more_info.

    Other workflow states may be important, but they do not
    ask the Observer to provide anything.
    """

    if isinstance(
        current_status,
        CaseStatus,
    ):
        current_status = (
            current_status.value
        )

    return (
        current_status
        == CaseStatus.NEEDS_MORE_INFO.value
    )


def get_observer_outcome(
    report,
) -> str | None:
    """
    Return the Observer-safe outcome text.

    Priority:

    1. A terminal closure label wins when the case is
       closed.

    2. An open case with an Observer-visible response state
       uses case_status.observer_label.

    3. Earlier workflow states do not yet have an outcome.

    Raw case_decision.response_type is deliberately never
    returned here.
    """

    closure_label = report.get(
        "closure_label"
    )

    if closure_label is not None:
        return closure_label

    current_status = report.get(
        "status"
    )

    if isinstance(
        current_status,
        CaseStatus,
    ):
        current_status = (
            current_status.value
        )

    if (
        current_status
        in OPEN_DECISION_STATUSES
    ):
        return report.get(
            "status_label"
        )

    return None


def get_observer_closure_summary(
    report,
) -> ObserverClosureSummary | None:
    """
    Return terminal closure information in an Observer-safe
    form.

    No coordinator identity or internal response decision is
    returned.
    """

    closure_label = report.get(
        "closure_label"
    )

    if closure_label is None:
        return None

    return ObserverClosureSummary(
        status=report[
            "status"
        ],
        closure_label=(
            closure_label
        ),
        public_note=report.get(
            "public_closure_note"
        ),
    )


def build_observer_report_projection(
    report,
    location=None,
) -> ObserverReportDetailResponse:
    """
    Build the complete Observer-facing report detail.

    The Observer may see their own precise location through
    reefcare_report_location(), but private storage keys and
    coordinator/case-decision details are not part of this
    projection.

    Iteration 2 extends the detail with:
    - evidence count
    - needsAttention
    - lastUpdatedAt
    """

    precise_location = None

    if location is not None:
        precise_location = (
            ObserverLocationResponse(
                latitude=location[
                    "latitude"
                ],

                longitude=location[
                    "longitude"
                ],

                uncertainty_metres=(
                    location[
                        "uncertainty_metres"
                    ]
                ),

                confidence_label=(
                    location[
                        "confidence_label"
                    ]
                ),

                source_label=(
                    location[
                        "source_label"
                    ]
                ),

                relocation_notes=(
                    location[
                        "relocation_notes"
                    ]
                ),
            )
        )

    return (
        ObserverReportDetailResponse(
            report_reference=(
                report[
                    "report_reference"
                ]
            ),

            threat_category=(
                report[
                    "threat"
                ]
            ),

            description=(
                report[
                    "description"
                ]
            ),

            observed_at=(
                report[
                    "observed_at"
                ]
            ),

            estimated_depth_metres=(
                report[
                    "estimated_depth_metres"
                ]
            ),

            general_location=(
                report[
                    "area"
                ]
            ),

            dive_site=(
                report.get(
                    "dive_site_name"
                )
            ),

            precise_location=(
                precise_location
            ),

            evidence_count=int(
                report.get(
                    "evidence_count",
                    0,
                )
            ),

            status=(
                report[
                    "status"
                ]
            ),

            status_label=(
                report[
                    "status_label"
                ]
            ),

            outcome=(
                get_observer_outcome(
                    report
                )
            ),

            needs_attention=(
                observer_needs_attention(
                    report[
                        "status"
                    ]
                )
            ),

            information_request_reason=(
                report.get(
                    "information_request_reason"
                )
            ),

            closure=(
                get_observer_closure_summary(
                    report
                )
            ),

            submitted_at=(
                report[
                    "submitted_at"
                ]
            ),

            last_updated_at=(
                report[
                    "last_updated_at"
                ]
            ),
        )
    )


def build_observer_timeline(
    *,
    report_reference: str,
    current_status,
    current_status_label: str,
    rows,
) -> ObserverTimelineResponse:
    """
    Build the Observer-facing timeline.

    reefcare_report_timeline() already guarantees the
    timeline contains only Observer-safe labels and
    timestamps.

    is_current is added to the final timeline row so the
    frontend does not need to independently infer the
    active point.

    currentStatus/currentStatusLabel remain explicit because
    the latest database state is authoritative even if old
    data contains an unusual or incomplete event history.
    """

    timeline: list[
        ObserverTimelineEvent
    ] = []

    row_count = len(
        rows
    )

    for index, row in enumerate(
        rows
    ):
        timeline.append(
            ObserverTimelineEvent(
                status_label=(
                    row[
                        "status_label"
                    ]
                ),

                occurred_at=(
                    row[
                        "occurred_at"
                    ]
                ),

                is_current=(
                    index
                    == row_count - 1
                ),
            )
        )

    return ObserverTimelineResponse(
        report_reference=(
            report_reference
        ),

        current_status=(
            current_status
        ),

        current_status_label=(
            current_status_label
        ),

        timeline=timeline,
    )


async def list_observer_reports(
    *,
    db: AsyncSession,
    observer_id: int,
    status_filter: (
        CaseStatus | None
    ) = None,
    from_date: (
        date | None
    ) = None,
    to_date: (
        date | None
    ) = None,
    page: int = 1,
    page_size: int = 20,
) -> ObserverReportListResponse:
    """
    Return the authenticated Observer's reports.

    Ownership filtering occurs inside PostgreSQL before the
    rows reach this service.

    Iteration 2 enriches each summary with:
    - observedAt
    - diveSite
    - needsAttention
    - lastUpdatedAt
    """

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise ObserverReportValidationError(
            "fromDate must be on or "
            "before toDate"
        )

    try:
        (
            rows,
            total,
        ) = (
            await report_repository
            .list_my_reports(
                db=db,

                observer_id=(
                    observer_id
                ),

                status_code=(
                    status_filter.value
                    if status_filter
                    else None
                ),

                from_date=(
                    from_date
                ),

                to_date=(
                    to_date
                ),

                page=page,

                page_size=(
                    page_size
                ),
            )
        )

        items = [
            ObserverReportSummary(
                report_reference=(
                    row[
                        "report_reference"
                    ]
                ),

                threat_category=(
                    row[
                        "threat"
                    ]
                ),

                general_location=(
                    row[
                        "area"
                    ]
                ),

                dive_site=(
                    row.get(
                        "dive_site_name"
                    )
                ),

                observed_at=(
                    row[
                        "observed_at"
                    ]
                ),

                status=(
                    row[
                        "status"
                    ]
                ),

                status_label=(
                    row[
                        "status_label"
                    ]
                ),

                outcome=(
                    get_observer_outcome(
                        row
                    )
                ),

                needs_attention=(
                    observer_needs_attention(
                        row[
                            "status"
                        ]
                    )
                ),

                submitted_at=(
                    row[
                        "submitted_at"
                    ]
                ),

                last_updated_at=(
                    row[
                        "last_updated_at"
                    ]
                ),
            )
            for row in rows
        ]

        return (
            ObserverReportListResponse(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
            )
        )

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to list observer reports"
        ) from exc


async def get_observer_report(
    *,
    db: AsyncSession,
    observer_id: int,
    report_reference: str,
) -> ObserverReportDetailResponse:
    """
    Return one report owned by the authenticated Observer.

    A report that belongs to another Observer is returned as
    NotFound rather than Forbidden, preventing report
    reference enumeration.

    Precise location remains independently authorised by
    reefcare_report_location().
    """

    try:
        report = (
            await report_repository
            .get_my_report(
                db=db,

                observer_id=(
                    observer_id
                ),

                report_reference=(
                    report_reference
                ),
            )
        )

        if report is None:
            raise NotFoundError(
                "Report not found"
            )

        location = (
            await get_report_location(
                db=db,

                report_reference=(
                    report_reference
                ),

                user_id=(
                    observer_id
                ),
            )
        )

        return (
            build_observer_report_projection(
                report=report,
                location=location,
            )
        )

    except NotFoundError:
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to load observer report"
        ) from exc


async def get_observer_report_timeline(
    *,
    db: AsyncSession,
    observer_id: int,
    report_reference: str,
) -> ObserverTimelineResponse:
    """
    Return Observer-safe plain-language status history.

    The report lookup occurs first.

    This means:
    - missing report -> 404
    - another Observer's report -> 404

    The caller therefore cannot enumerate valid report
    references belonging to other users.

    reefcare_report_timeline() then supplies only safe
    status labels and timestamps.
    """

    try:
        report = (
            await report_repository
            .get_my_report(
                db=db,

                observer_id=(
                    observer_id
                ),

                report_reference=(
                    report_reference
                ),
            )
        )

        if report is None:
            raise NotFoundError(
                "Report not found"
            )

        rows = (
            await report_repository
            .get_report_timeline(
                db=db,

                observer_id=(
                    observer_id
                ),

                report_reference=(
                    report_reference
                ),
            )
        )

        return build_observer_timeline(
            report_reference=(
                report_reference
            ),

            current_status=(
                report[
                    "status"
                ]
            ),

            current_status_label=(
                report[
                    "status_label"
                ]
            ),

            rows=rows,
        )

    except NotFoundError:
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to load report timeline"
        ) from exc