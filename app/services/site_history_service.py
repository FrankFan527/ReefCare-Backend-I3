# ---------------------------------------------------------------------------
# US8.1 Coordinator site history — policy.
#
# Assembles one chronological history for a configured dive site from two
# canonical sources: eligible observations, and the E7 follow-up records on
# those observations.
#
# Two things this service is careful about:
#
#   AC3  an observation carries the assessment state it actually reached.
#        Nothing here promotes a report to "accepted" because its case was
#        closed, or because a follow-up happened to be recorded on it.
#
#   AC5  no history is reported as no history, never as a healthy site. A
#        site with nothing recorded is a site nobody has reported, which says
#        something about ReefCare's coverage and nothing about the reef.
# ---------------------------------------------------------------------------

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import site_history_repository as the_repository
from app.schemas.site_history import (
    THE_ASSESSMENT_STATE_LABELS,
    AssessmentState,
    SiteHistoryCounts,
    SiteHistoryItem,
    SiteHistoryRecordType,
    SiteHistoryResponse,
    SiteHistoryState,
)


# Below this many eligible records, the history is reported as insufficient
# rather than shown. One record is a data point, not a history, and a single
# entry invites a conclusion it cannot support.
THE_MINIMUM_RECORDS_FOR_HISTORY: int = 2


THE_INSUFFICIENT_HISTORY_MESSAGE: str = (
    "There is not enough recorded ReefCare history for this site to show a "
    "meaningful picture. This reflects what has been reported, not the "
    "condition of the reef."
)


def build_history_message(
    the_record_count: int,
    the_observation_count: int,
    the_follow_up_count: int,
) -> str:
    the_parts: list[str] = [
        f"{the_observation_count} "
        f"{'observation' if the_observation_count == 1 else 'observations'}"
    ]

    if the_follow_up_count:
        the_parts.append(
            f"{the_follow_up_count} follow-up "
            f"{'record' if the_follow_up_count == 1 else 'records'}"
        )

    return (
        f"{the_record_count} recorded "
        f"{'entry' if the_record_count == 1 else 'entries'} for this site: "
        + " and ".join(the_parts)
        + "."
    )


def to_observation_item(
    the_row: dict,
) -> SiteHistoryItem:
    the_state = AssessmentState(the_row["assessment_state"])

    return SiteHistoryItem(
        record_type=SiteHistoryRecordType.OBSERVATION,
        occurred_at=the_row["observed_at"],
        occurred_on=the_row["observed_at"].date() if the_row["observed_at"] else None,
        threat_category_code=the_row["threat_category_code"],
        threat_category_label=the_row["threat_category_label"],
        assessment_state=the_state,
        assessment_state_label=THE_ASSESSMENT_STATE_LABELS[the_state],
        # US1.3 AC2: the reference is only shown for a case this Coordinator
        # owns. The entry itself still appears, so the site history is honest
        # about work other Coordinators are doing.
        report_reference=(
            the_row["report_reference"] if the_row["owned_by_you"] else None
        ),
        owned_by_you=bool(the_row["owned_by_you"]),
        recorded_at=the_row["submitted_at"],
    )


def to_follow_up_item(
    the_row: dict,
) -> SiteHistoryItem:
    the_record_type = {
        "action": SiteHistoryRecordType.ACTION,
        "monitoring": SiteHistoryRecordType.MONITORING,
        "sourced_outcome": SiteHistoryRecordType.SOURCED_OUTCOME,
    }[the_row["follow_up_type"]]

    return SiteHistoryItem(
        record_type=the_record_type,
        occurred_on=the_row["action_date"],
        follow_up_type=the_row["follow_up_type"],
        follow_up_state=the_row["follow_up_state"],
        condition_code=the_row["condition_code"],
        condition_label=the_row["condition_label"],
        responsible_team=the_row["responsible_team"],
        recorded_outcome=the_row["recorded_outcome"],
        next_follow_up_required=the_row["next_follow_up_required"],
        next_follow_up_date=the_row["next_follow_up_date"],
        report_reference=(
            the_row["report_reference"] if the_row["owned_by_you"] else None
        ),
        owned_by_you=bool(the_row["owned_by_you"]),
        recorded_at=the_row["created_at"],
    )


def sort_key(
    the_item: SiteHistoryItem,
) -> tuple:
    """
    Chronological by when the event happened, falling back to when it was
    recorded. An observation has a timestamp; a follow-up has a date, so both
    are compared at day precision first.
    """

    the_day = the_item.occurred_on or the_item.recorded_at.date()

    return (the_day, the_item.recorded_at)


def count_records(
    the_items: list[SiteHistoryItem],
) -> SiteHistoryCounts:
    the_counts = SiteHistoryCounts()

    the_by_state: dict[str, int] = {}

    for the_item in the_items:
        if the_item.record_type == SiteHistoryRecordType.OBSERVATION:
            the_counts.observations += 1

            if the_item.assessment_state is not None:
                the_key = the_item.assessment_state.value
                the_by_state[the_key] = the_by_state.get(the_key, 0) + 1

        elif the_item.record_type == SiteHistoryRecordType.ACTION:
            the_counts.actions += 1

        elif the_item.record_type == SiteHistoryRecordType.MONITORING:
            the_counts.monitoring_visits += 1

        else:
            the_counts.sourced_outcomes += 1

    the_counts.observations_by_assessment_state = the_by_state

    return the_counts


def first_and_last_day(
    the_items: list[SiteHistoryItem],
) -> tuple[date | None, date | None]:
    if not the_items:
        return None, None

    the_days = [
        the_item.occurred_on or the_item.recorded_at.date()
        for the_item in the_items
    ]

    return min(the_days), max(the_days)


async def get_site_history(
    db: AsyncSession,
    dive_site_id: int,
    coordinator_id: int,
) -> SiteHistoryResponse:
    """
    The recorded history for one configured site.

    Any Case Coordinator may read this. It carries no report descriptions, no
    evidence, no coordinates and no Observer identity, and a report reference
    appears only for cases this Coordinator owns.
    """

    the_site = await the_repository.get_site_identity(db=db, dive_site_id=dive_site_id)

    if the_site is None:
        raise NotFoundError(f"Dive site {dive_site_id} was not found")

    the_observations = await the_repository.list_site_observations(
        db=db,
        dive_site_id=dive_site_id,
        coordinator_id=coordinator_id,
    )

    the_follow_ups = await the_repository.list_site_follow_ups(
        db=db,
        dive_site_id=dive_site_id,
        coordinator_id=coordinator_id,
    )

    the_items = [to_observation_item(the_row) for the_row in the_observations]
    the_items += [to_follow_up_item(the_row) for the_row in the_follow_ups]

    the_items.sort(key=sort_key)

    if len(the_items) < THE_MINIMUM_RECORDS_FOR_HISTORY:
        # AC5: say there is not enough history. Returning the one or two
        # records with a confident framing would invite exactly the reading
        # this state exists to prevent.
        return SiteHistoryResponse(
            dive_site_id=the_site["dive_site_id"],
            site_name=the_site["site_name"],
            public_area_label=the_site["public_area_label"],
            state=SiteHistoryState.INSUFFICIENT_HISTORY,
            message=THE_INSUFFICIENT_HISTORY_MESSAGE,
            counts=count_records(the_items),
        )

    the_first_day, the_last_day = first_and_last_day(the_items)

    return SiteHistoryResponse(
        dive_site_id=the_site["dive_site_id"],
        site_name=the_site["site_name"],
        public_area_label=the_site["public_area_label"],
        state=SiteHistoryState.AVAILABLE,
        message=build_history_message(
            the_record_count=len(the_items),
            the_observation_count=len(the_observations),
            the_follow_up_count=len(the_follow_ups),
        ),
        first_record_on=the_first_day,
        last_record_on=the_last_day,
        counts=count_records(the_items),
        items=the_items,
    )
