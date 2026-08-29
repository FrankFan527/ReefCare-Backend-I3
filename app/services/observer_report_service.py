from datetime import date

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CaseStatus
from app.core.exceptions import (
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories import report_repository
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


class ObserverReportValidationError(ValueError):
    """Raised when My Reports filter input is internally inconsistent."""


def get_observer_outcome(report) -> str | None:
    """
    Return the simplified observer-safe outcome.

    The database function reefcare_my_reports() already returns
    closure_reason.observer_label, so no Python status/closure-label
    map is maintained here.
    """

    return report.get("closure_label")


def get_observer_closure_summary(
    report,
) -> ObserverClosureSummary | None:
    """
    Build the observer-facing closure summary.

    Only the closure label and the note attached to the closing event
    are exposed. Internal coordinator decision fields are intentionally
    absent from the projection.
    """

    closure_label = report.get(
        "closure_label"
    )

    if closure_label is None:
        return None

    return ObserverClosureSummary(
        status=report["status"],
        closure_label=closure_label,
        public_note=report.get(
            "public_closure_note"
        ),
    )


def build_observer_report_projection(
    report,
    location=None,
) -> ObserverReportDetailResponse:
    """
    Shape an already observer-scoped database row into the public API
    contract.

    This function deliberately has no fields for:
    - coordinator identity
    - internal case-status labels
    - case-decision reasoning
    - private evidence object keys

    Precise location is included only when it has been returned by
    reefcare_report_location(reference, observer_id), whose database
    authorization rule is authoritative.
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
                source_label=location[
                    "source_label"
                ],
                relocation_notes=(
                    location[
                        "relocation_notes"
                    ]
                ),
            )
        )

    return ObserverReportDetailResponse(
        report_reference=report[
            "report_reference"
        ],
        threat_category=report["threat"],
        description=report["description"],
        observed_at=report["observed_at"],
        estimated_depth_metres=report[
            "estimated_depth_metres"
        ],
        general_location=report["area"],
        dive_site=report.get(
            "dive_site_name"
        ),
        precise_location=precise_location,
        status=report["status"],
        status_label=report[
            "status_label"
        ],
        outcome=get_observer_outcome(
            report
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
        submitted_at=report[
            "submitted_at"
        ],
    )


def build_observer_timeline(
    *,
    report_reference: str,
    rows,
) -> ObserverTimelineResponse:
    """
    Shape deterministic observer-safe timeline rows returned by
    reefcare_report_timeline().
    """

    return ObserverTimelineResponse(
        report_reference=report_reference,
        timeline=[
            ObserverTimelineEvent(
                status_label=row[
                    "status_label"
                ],
                occurred_at=row[
                    "occurred_at"
                ],
            )
            for row in rows
        ],
    )


async def list_observer_reports(
    *,
    db: AsyncSession,
    observer_id: int,
    status_filter: CaseStatus | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ObserverReportListResponse:
    """
    List only the authenticated observer's reports.

    Observer isolation starts in PostgreSQL through
    reefcare_my_reports(observer_id). Filtering and pagination are then
    applied to that already-scoped result set.
    """

    if (
        from_date is not None
        and to_date is not None
        and from_date > to_date
    ):
        raise ObserverReportValidationError(
            "fromDate must be on or before toDate"
        )

    try:
        rows, total = (
            await report_repository
            .list_my_reports(
                db=db,
                observer_id=observer_id,
                status_code=(
                    status_filter.value
                    if status_filter
                    else None
                ),
                from_date=from_date,
                to_date=to_date,
                page=page,
                page_size=page_size,
            )
        )

        items = [
            ObserverReportSummary(
                report_reference=row[
                    "report_reference"
                ],
                threat_category=row[
                    "threat"
                ],
                general_location=row[
                    "area"
                ],
                status=row["status"],
                status_label=row[
                    "status_label"
                ],
                outcome=(
                    get_observer_outcome(
                        row
                    )
                ),
                submitted_at=row[
                    "submitted_at"
                ],
            )
            for row in rows
        ]

        return ObserverReportListResponse(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
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
    Return one report owned by the authenticated observer.

    The repository first scopes through reefcare_my_reports(), and the
    precise-location lookup is separately authorized by
    reefcare_report_location(). A report belonging to another observer
    is therefore indistinguishable from a missing report at this API.
    """

    try:
        report = (
            await report_repository
            .get_my_report(
                db=db,
                observer_id=observer_id,
                report_reference=(
                    report_reference
                ),
            )
        )

        if report is None:
            raise NotFoundError(
                "Report not found"
            )

        location = await get_report_location(
            db=db,
            report_reference=(
                report_reference
            ),
            user_id=observer_id,
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
    Return the observer-safe plain-language status timeline.

    A scoped report lookup is performed first so an empty timeline is
    not used to guess whether another observer's report exists.
    """

    try:
        report = (
            await report_repository
            .get_my_report(
                db=db,
                observer_id=observer_id,
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
                observer_id=observer_id,
                report_reference=(
                    report_reference
                ),
            )
        )

        return build_observer_timeline(
            report_reference=(
                report_reference
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
