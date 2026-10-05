from datetime import (
    date,
    datetime,
    timezone,
)

import pytest

from app.core.enums import (
    CaseStatus,
)
from app.schemas.report import (
    ObserverContributionSummary,
)
from app.services.observer_report_service import (
    build_action_contribution,
    build_observer_report_projection,
    build_observer_timeline,
    build_status_contribution,
)


NOW = datetime(
    2026,
    10,
    4,
    12,
    0,
    tzinfo=timezone.utc,
)


def the_base_report(
    *,
    status=CaseStatus.UNDER_REVIEW,
    status_label="Under review",
):
    return {
        "report_reference":
            "RC-E6-001",

        "threat":
            "Ghost net",

        "description":
            "Discarded fishing net observed on reef.",

        "observed_at":
            datetime(
                2026,
                10,
                1,
                3,
                0,
                tzinfo=timezone.utc,
            ),

        "estimated_depth_metres":
            8.0,

        "area":
            "Redang Island",

        "dive_site_name":
            "Example Reef",

        "evidence_count":
            2,

        "status":
            status,

        "status_label":
            status_label,

        "closure_label":
            None,

        "public_closure_note":
            None,

        "information_request_reason":
            None,

        "submitted_at":
            datetime(
                2026,
                10,
                1,
                4,
                0,
                tzinfo=timezone.utc,
            ),

        "last_updated_at":
            NOW,
    }


def test_planned_action_is_not_described_as_completed():
    action = {
        "action_state":
            "action_planned",

        "action_type_label":
            "Debris removal",

        "follow_up_type":
            "intervention",

        "recorded_outcome":
            None,

        "created_at":
            NOW,

        "next_follow_up_required":
            True,

        "next_follow_up_date":
            date(
                2026,
                10,
                10,
            ),
    }

    result = build_action_contribution(
        action
    )

    assert isinstance(
        result,
        ObserverContributionSummary,
    )

    assert (
        result.contribution_type
        == "action"
    )

    assert (
        result.state
        == "planned"
    )

    assert "planned" in (
        result.label.lower()
    )

    assert "completed" not in (
        result.label.lower()
    )

    assert (
        result.next_follow_up_required
        is True
    )


def test_taken_action_is_described_as_completed():
    action = {
        "action_state":
            "action_taken",

        "action_type_label":
            "Debris removal",

        "follow_up_type":
            "intervention",

        "recorded_outcome":
            "Ghost net removed from the reef.",

        "created_at":
            NOW,

        "next_follow_up_required":
            False,

        "next_follow_up_date":
            None,
    }

    result = build_action_contribution(
        action
    )

    assert (
        result.contribution_type
        == "action"
    )

    assert (
        result.state
        == "completed"
    )

    assert "completed" in (
        result.label.lower()
    )

    assert (
        result.detail
        == "Ghost net removed from the reef."
    )


def test_monitoring_follow_up_is_projected_safely():
    action = {
        "action_state":
            "recorded",

        "action_type_label":
            "Site monitoring",

        "follow_up_type":
            "monitoring",

        "recorded_outcome":
            "Site condition reviewed.",

        "created_at":
            NOW,

        "next_follow_up_required":
            True,

        "next_follow_up_date":
            date(
                2026,
                11,
                1,
            ),
    }

    result = build_action_contribution(
        action
    )

    assert (
        result.contribution_type
        == "monitoring"
    )

    assert (
        result.state
        == "recorded"
    )

    assert "monitoring" in (
        result.label.lower()
    )

    assert (
        result.detail
        == "Site condition reviewed."
    )


def test_referral_status_does_not_claim_external_action():
    report = the_base_report(
        status=CaseStatus.REFERRED,
        status_label="Referred for follow-up",
    )

    result = build_status_contribution(
        report
    )

    assert (
        result.contribution_type
        == "referral"
    )

    assert (
        result.state
        == "referred"
    )

    assert "referred" in (
        result.label.lower()
    )

    assert "completed" not in (
        result.label.lower()
    )

    assert "acted" not in (
        result.label.lower()
    )


def test_monitoring_status_is_not_described_as_completed():
    report = the_base_report(
        status=CaseStatus.MONITORING,
        status_label="Being monitored",
    )

    result = build_status_contribution(
        report
    )

    assert (
        result.contribution_type
        == "monitoring"
    )

    assert (
        result.state
        == "ongoing"
    )

    assert "ongoing" in (
        result.label.lower()
    )

    assert "completed" not in (
        result.label.lower()
    )


def test_response_planned_and_complete_are_distinct():
    planned = build_status_contribution(
        the_base_report(
            status=(
                CaseStatus
                .RESPONSE_PLANNED
            ),
            status_label=(
                "Response planned"
            ),
        )
    )

    completed = build_status_contribution(
        the_base_report(
            status=(
                CaseStatus
                .RESPONSE_COMPLETE
            ),
            status_label=(
                "Response completed"
            ),
        )
    )

    assert planned.state == "planned"
    assert completed.state == "completed"

    assert (
        planned.label
        != completed.label
    )


def test_report_detail_includes_publishable_contribution():
    report = the_base_report(
        status=(
            CaseStatus
            .RESPONSE_COMPLETE
        ),
        status_label=(
            "Response completed"
        ),
    )

    action = {
        "action_state":
            "action_taken",

        "action_type_label":
            "Debris removal",

        "follow_up_type":
            "intervention",

        "recorded_outcome":
            "Threat material was removed.",

        "created_at":
            NOW,

        "next_follow_up_required":
            False,

        "next_follow_up_date":
            None,
    }

    response = (
        build_observer_report_projection(
            report=report,
            location=None,
            contribution=action,
        )
    )

    assert (
        response.contribution
        is not None
    )

    assert (
        response.contribution.state
        == "completed"
    )

    assert (
        response.contribution.detail
        == "Threat material was removed."
    )


def test_report_detail_without_contribution_remains_valid():
    report = the_base_report()

    response = (
        build_observer_report_projection(
            report=report,
            location=None,
            contribution=None,
        )
    )

    assert (
        response.report_reference
        == "RC-E6-001"
    )

    assert (
        response.contribution
        is None
    )


def test_timeline_includes_safe_related_incident_event():
    report = the_base_report()

    rows = [
        {
            "status_label":
                "Report received",

            "occurred_at":
                datetime(
                    2026,
                    10,
                    1,
                    4,
                    0,
                    tzinfo=timezone.utc,
                ),
        },
        {
            "status_label":
                "Under review",

            "occurred_at":
                datetime(
                    2026,
                    10,
                    2,
                    4,
                    0,
                    tzinfo=timezone.utc,
                ),
        },
    ]

    related = {
        "occurred_at":
            datetime(
                2026,
                10,
                3,
                4,
                0,
                tzinfo=timezone.utc,
            ),
    }

    response = build_observer_timeline(
        report_reference=(
            report[
                "report_reference"
            ]
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

        related_incident=related,

        contribution=None,
    )

    related_events = [
        event
        for event
        in response.timeline
        if (
            event.event_type
            == "related_incident"
        )
    ]

    assert (
        len(related_events)
        == 1
    )

    assert (
        related_events[0]
        .status_label
        ==
        "Linked to an existing report "
        "of the same issue"
    )

    # The safe event must contain no report reference,
    # incident id or user identity.
    payload = (
        related_events[0]
        .model_dump()
    )

    assert (
        "report_reference"
        not in payload
    )

    assert (
        "incident_id"
        not in payload
    )

    assert (
        "observer_id"
        not in payload
    )

    assert (
        "coordinator_id"
        not in payload
    )


def test_timeline_follow_up_does_not_replace_current_status():
    report = the_base_report()

    status_time = datetime(
        2026,
        10,
        2,
        4,
        0,
        tzinfo=timezone.utc,
    )

    follow_up_time = datetime(
        2026,
        10,
        4,
        4,
        0,
        tzinfo=timezone.utc,
    )

    rows = [
        {
            "status_label":
                "Under review",

            "occurred_at":
                status_time,
        }
    ]

    action = {
        "action_state":
            "action_planned",

        "action_type_label":
            "Follow-up inspection",

        "follow_up_type":
            "monitoring",

        "recorded_outcome":
            None,

        "created_at":
            follow_up_time,

        "next_follow_up_required":
            True,

        "next_follow_up_date":
            date(
                2026,
                10,
                12,
            ),
    }

    response = build_observer_timeline(
        report_reference=(
            report[
                "report_reference"
            ]
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

        related_incident=None,

        contribution=action,
    )

    status_events = [
        event
        for event
        in response.timeline
        if event.event_type == "status"
    ]

    follow_up_events = [
        event
        for event
        in response.timeline
        if event.event_type == "follow_up"
    ]

    assert len(status_events) == 1
    assert len(follow_up_events) == 1

    assert (
        status_events[0].is_current
        is True
    )

    assert (
        follow_up_events[0].is_current
        is False
    )


def test_timeline_is_chronologically_sorted():
    report = the_base_report()

    rows = [
        {
            "status_label":
                "Report received",

            "occurred_at":
                datetime(
                    2026,
                    10,
                    1,
                    4,
                    0,
                    tzinfo=timezone.utc,
                ),
        },
        {
            "status_label":
                "Under review",

            "occurred_at":
                datetime(
                    2026,
                    10,
                    4,
                    4,
                    0,
                    tzinfo=timezone.utc,
                ),
        },
    ]

    related = {
        "occurred_at":
            datetime(
                2026,
                10,
                2,
                4,
                0,
                tzinfo=timezone.utc,
            ),
    }

    response = build_observer_timeline(
        report_reference=(
            report[
                "report_reference"
            ]
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

        related_incident=related,

        contribution=None,
    )

    timestamps = [
        event.occurred_at
        for event
        in response.timeline
    ]

    assert timestamps == sorted(
        timestamps
    )