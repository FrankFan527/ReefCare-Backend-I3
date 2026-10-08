# ---------------------------------------------------------------------------
# Observer report tracking (US6.1 / US6.2 / US6.4).
#
# This service owns the Observer-facing projection and validation rules.
#
# The database remains the ownership boundary:
#
#   reefcare_my_reports(observer_id)
#   reefcare_report_timeline(report_reference, observer_id)
#   reefcare_report_location(report_reference, user_id)
#
# This layer deliberately does not expose:
# - coordinator identity
# - internal decision vocabulary
# - private evidence storage references
# - internal incident ids
# - another Observer's report reference
# - internal action notes
#
# Iteration 3 E6 extends the existing tracking layer with:
#
# - human-confirmed related-incident feedback
# - Observer-safe E7 follow-up/contribution outcomes
#
# E6 is private feedback to the submitting Observer.
# It does not depend on case_action.is_publishable.
#
# is_publishable belongs only to the E8 public-activity
# publication boundary.
#
# No new workflow state is created here. Everything shown to the Observer is
# projected from facts that already exist in E5/E7.
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
    ObserverContributionSummary,
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


# ---------------------------------------------------------------------------
# Existing Observer-safe outcome states.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Iteration 3 — E6 contribution projection.
# ---------------------------------------------------------------------------


def build_action_contribution(
    action,
) -> ObserverContributionSummary | None:
    """
    Convert the latest valid E7 case_action into an
    Observer-safe private contribution summary.

    E6 private feedback does not depend on
    case_action.is_publishable. That flag is reserved for
    the E8 public-activity publication boundary.

    This function never infers that an action happened when
    the stored action_state says only that it was planned.

    Sourced external outcomes are identified separately
    from ReefCare actions so an external report is never
    presented as a ReefCare-completed intervention.

    Internal notes, coordinator identity, responsible team,
    source_reference and reviewer identity are deliberately
    excluded.
    """

    if action is None:
        return None

    action_state = action.get(
        "action_state"
    )

    action_type_label = action.get(
        "action_type_label"
    )

    follow_up_type = (
        action.get(
            "follow_up_type"
        )
        or ""
    )

    follow_up_normalised = (
        str(
            follow_up_type
        )
        .strip()
        .lower()
    )

    recording_level = (
        action.get(
            "recording_level"
        )
        or ""
    )

    recording_level_normalised = (
        str(
            recording_level
        )
        .strip()
        .lower()
    )

    recorded_outcome = action.get(
        "recorded_outcome"
    )

    recorded_at = (
        action.get(
            "created_at"
        )
    )

    next_follow_up_required = bool(
        action.get(
            "next_follow_up_required",
            False,
        )
    )

    next_follow_up_date = action.get(
        "next_follow_up_date"
    )

    # ---------------------------------------------------------------
    # Sourced external outcome.
    #
    # This is deliberately checked before action_state.
    #
    # A sourced_outcome is information reported from an
    # external organisation/source. It does not prove that
    # ReefCare itself performed or completed the action.
    # ---------------------------------------------------------------

    if (
        follow_up_normalised
        == "sourced_outcome"
        or recording_level_normalised
        == "externally_sourced"
    ):
        return ObserverContributionSummary(
            contribution_type=(
                "external_outcome"
            ),

            state="reported",

            label=(
                "An externally reported follow-up "
                "outcome has been recorded for "
                "this report."
            ),

            detail=recorded_outcome,

            recorded_at=recorded_at,

            next_follow_up_required=(
                next_follow_up_required
            ),

            next_follow_up_date=(
                next_follow_up_date
            ),
        )

    # ---------------------------------------------------------------
    # Planned conservation action.
    #
    # This must never be described as completed.
    # ---------------------------------------------------------------

    if action_state == "action_planned":
        return ObserverContributionSummary(
            contribution_type="action",

            state="planned",

            label=(
                "A conservation action has been "
                "planned in response to this report."
            ),

            detail=(
                action_type_label
                or recorded_outcome
            ),

            recorded_at=recorded_at,

            next_follow_up_required=(
                next_follow_up_required
            ),

            next_follow_up_date=(
                next_follow_up_date
            ),
        )

    # ---------------------------------------------------------------
    # Completed / recorded conservation action.
    # ---------------------------------------------------------------

    if action_state == "action_taken":
        return ObserverContributionSummary(
            contribution_type="action",

            state="completed",

            label=(
                "A conservation action has been "
                "recorded as completed."
            ),

            detail=(
                recorded_outcome
                or action_type_label
            ),

            recorded_at=recorded_at,

            next_follow_up_required=(
                next_follow_up_required
            ),

            next_follow_up_date=(
                next_follow_up_date
            ),
        )

    # ---------------------------------------------------------------
    # Monitoring-oriented E7 follow-up.
    #
    # We do not claim monitoring is complete merely because
    # a follow-up record exists.
    # ---------------------------------------------------------------

    if (
        "monitor"
        in follow_up_normalised
    ):
        return ObserverContributionSummary(
            contribution_type="monitoring",

            state="recorded",

            label=(
                "Your report contributed to reef "
                "monitoring and follow-up."
            ),

            detail=recorded_outcome,

            recorded_at=recorded_at,

            next_follow_up_required=(
                next_follow_up_required
            ),

            next_follow_up_date=(
                next_follow_up_date
            ),
        )

    # ---------------------------------------------------------------
    # Generic valid E7 follow-up.
    #
    # Still truthful: it says only that follow-up was
    # recorded, not that a specific conservation outcome
    # occurred.
    # ---------------------------------------------------------------

    return ObserverContributionSummary(
        contribution_type="follow_up",

        state="recorded",

        label=(
            "A follow-up outcome has been recorded "
            "for this report."
        ),

        detail=recorded_outcome,

        recorded_at=recorded_at,

        next_follow_up_required=(
            next_follow_up_required
        ),

        next_follow_up_date=(
            next_follow_up_date
        ),
    )


def build_status_contribution(
    report,
) -> ObserverContributionSummary | None:
    """
    Build a conservative contribution summary from the
    report's already-recorded workflow state.

    Used only when there is no valid E7 action/follow-up row
    available for the private Observer projection.

    The wording deliberately avoids claiming more than the
    stored state proves.
    """

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

    recorded_at = report.get(
        "last_updated_at"
    )

    if (
        current_status
        == CaseStatus.REFERRED.value
    ):
        return ObserverContributionSummary(
            contribution_type="referral",
            state="referred",
            label=(
                "Your report was referred or shared "
                "for follow-up."
            ),
            detail=None,
            recorded_at=recorded_at,
        )

    if (
        current_status
        == CaseStatus.MONITORING.value
    ):
        return ObserverContributionSummary(
            contribution_type="monitoring",
            state="ongoing",
            label=(
                "Your report is contributing to "
                "ongoing monitoring."
            ),
            detail=None,
            recorded_at=recorded_at,
        )

    if (
        current_status
        == CaseStatus.RESPONSE_PLANNED.value
    ):
        return ObserverContributionSummary(
            contribution_type="action",
            state="planned",
            label=(
                "A conservation response has been "
                "planned."
            ),
            detail=None,
            recorded_at=recorded_at,
        )

    if (
        current_status
        == CaseStatus.RESPONSE_COMPLETE.value
    ):
        return ObserverContributionSummary(
            contribution_type="action",
            state="completed",
            label=(
                "A conservation response has been "
                "recorded as completed."
            ),
            detail=None,
            recorded_at=recorded_at,
        )

    if (
        current_status
        == CaseStatus.CLOSED_LOGGED.value
    ):
        return ObserverContributionSummary(
            contribution_type="site_history",
            state="recorded",
            label=(
                "Your report has been retained as "
                "part of ReefCare's site history."
            ),
            detail=None,
            recorded_at=recorded_at,
        )

    return None


def get_observer_contribution_summary(
    *,
    report,
    action=None,
) -> ObserverContributionSummary | None:
    """
    Return the strongest truthful contribution projection.

    The latest valid E7 action/follow-up record is preferred.

    E6 private feedback does not depend on
    case_action.is_publishable.

    If no valid E7 record exists, a small set of
    already-recorded case statuses may still support a
    truthful contribution message.
    """

    action_contribution = (
        build_action_contribution(
            action
        )
    )

    if action_contribution is not None:
        return action_contribution

    return build_status_contribution(
        report
    )


def build_observer_report_projection(
    report,
    location=None,
    contribution=None,
) -> ObserverReportDetailResponse:
    """
    Build the complete Observer-facing report detail.

    The Observer may see their own precise location through
    reefcare_report_location(), but private storage keys and
    coordinator/case-decision details are not part of this
    projection.

    Iteration 3 adds:
    - truthful contribution/follow-up summary
    - no invented conservation outcome
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

    contribution_summary = (
        get_observer_contribution_summary(
            report=report,
            action=contribution,
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

            contribution=(
                contribution_summary
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
    related_incident=None,
    contribution=None,
) -> ObserverTimelineResponse:
    """
    Build the Observer-facing timeline.

    Existing PostgreSQL timeline rows contain only
    Observer-safe labels and timestamps.

    Iteration 3 additionally allows:
    - a human-confirmed same-incident explanation
    - one latest valid follow-up/contribution event

    Neither extension exposes another report, another
    Observer, Coordinator identity or internal incident id.

    is_current remains attached only to the latest ordinary
    status event. Impact/follow-up entries are informative
    events rather than case states.
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
                event_type="status",

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

    # ---------------------------------------------------------------
    # Human-confirmed same incident.
    #
    # Do not expose:
    # - related report reference
    # - incident id
    # - another Observer
    # ---------------------------------------------------------------

    if related_incident is not None:
        timeline.append(
            ObserverTimelineEvent(
                event_type=(
                    "related_incident"
                ),

                status_label=(
                    "Linked to an existing report "
                    "of the same issue"
                ),

                occurred_at=(
                    related_incident[
                        "occurred_at"
                    ]
                ),

                is_current=False,
            )
        )

    # ---------------------------------------------------------------
    # Latest valid E7 follow-up for private Observer feedback.
    # ---------------------------------------------------------------

    contribution_summary = (
        build_action_contribution(
            contribution
        )
    )

    if (
        contribution_summary is not None
        and
        contribution_summary.recorded_at
        is not None
    ):
        timeline.append(
            ObserverTimelineEvent(
                event_type="follow_up",

                status_label=(
                    contribution_summary.label
                ),

                occurred_at=(
                    contribution_summary
                    .recorded_at
                ),

                is_current=False,
            )
        )

    # Timeline entries may come from different append-only
    # sources, so restore chronological ordering here.
    timeline.sort(
        key=lambda event:
            event.occurred_at
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

    Iteration 3 also loads only the latest valid E7
    contribution/follow-up record.

    E6 private Observer feedback does not depend on
    case_action.is_publishable.
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

        contribution = (
            await report_repository
            .get_observer_contribution(
                db=db,

                observer_id=(
                    observer_id
                ),

                report_reference=(
                    report_reference
                ),
            )
        )

        return (
            build_observer_report_projection(
                report=report,
                location=location,
                contribution=contribution,
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
    Return Observer-safe plain-language history.

    The report lookup occurs first.

    Therefore:
    - missing report -> 404
    - another Observer's report -> 404

    The caller cannot enumerate valid report references
    belonging to other users.

    Iteration 3 adds two optional impact events:
    - confirmed related incident
    - publishable E7 follow-up

    Neither event exposes another Observer or internal case
    information.
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

        related_incident = (
            await report_repository
            .get_observer_related_incident_event(
                db=db,

                observer_id=(
                    observer_id
                ),

                report_reference=(
                    report_reference
                ),
            )
        )

        contribution = (
            await report_repository
            .get_observer_contribution(
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

            related_incident=(
                related_incident
            ),

            contribution=(
                contribution
            ),
        )

    except NotFoundError:
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to load report timeline"
        ) from exc