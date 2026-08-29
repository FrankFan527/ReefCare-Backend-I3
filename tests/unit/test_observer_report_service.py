from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.core.enums import CaseStatus
from app.core.exceptions import NotFoundError
from app.repositories import report_repository
from app.services import observer_report_service
from app.services.observer_report_service import (
    ObserverReportValidationError,
    build_observer_report_projection,
    build_observer_timeline,
    get_observer_report,
    list_observer_reports,
)


NOW = datetime(
    2026,
    8,
    29,
    6,
    0,
    tzinfo=timezone.utc,
)


def test_projection_exposes_only_observer_safe_fields():
    report = {
        "report_reference": "RC-0003",
        "threat": "Marine debris",
        "area": "Perhentian Islands",
        "status": "closed_no_partner",
        "status_label": (
            "Recorded, no active response programme "
            "currently covers this site"
        ),
        "closure_label": (
            "Recorded and kept — no active response "
            "programme currently covers this site"
        ),
        "observed_at": NOW,
        "estimated_depth_metres": 20.0,
        "description": (
            "Plastic sacks and rope on the reef."
        ),
        "dive_site_name": (
            "Temple of the Sea (Tokong Laut)"
        ),
        "information_request_reason": None,
        "public_closure_note": (
            "Retained for site history."
        ),
        "submitted_at": NOW,

        # These should NEVER appear to observer.
        "claimed_by_user_id": 999,
        "decision_note": (
            "internal-only reasoning"
        ),
        "file_reference": (
            "private/object/key.jpg"
        ),
    }

    location = {
        "latitude": 5.9,
        "longitude": 102.7,
        "uncertainty_metres": 1000,
        "confidence_label": (
            "Within approximately 1 km"
        ),
        "source_label": (
            "Manually dropped map pin"
        ),
        "relocation_notes": (
            "North face of the pinnacle."
        ),
    }

    response = (
        build_observer_report_projection(
            report=report,
            location=location,
        )
    )

    payload = response.model_dump(
        by_alias=True,
        mode="json",
    )

    assert (
        payload["reportReference"]
        == "RC-0003"
    )

    assert (
        payload["status"]
        == "closed_no_partner"
    )

    assert (
        payload["preciseLocation"]
        ["uncertaintyMetres"]
        == 1000
    )

    assert "claimedByUserId" not in payload
    assert "decisionNote" not in payload
    assert "fileReference" not in payload


def test_timeline_projection_uses_plain_language_labels():
    response = build_observer_timeline(
        report_reference="RC-0002",
        rows=[
            {
                "status_label":
                    "Report received",
                "occurred_at": NOW,
            },
            {
                "status_label":
                    (
                        "A case coordinator has "
                        "your report"
                    ),
                "occurred_at": NOW,
            },
            {
                "status_label":
                    "Being reviewed",
                "occurred_at": NOW,
            },
        ],
    )

    assert (
        response.report_reference
        == "RC-0002"
    )

    assert [
        event.status_label
        for event in response.timeline
    ] == [
        "Report received",
        (
            "A case coordinator has "
            "your report"
        ),
        "Being reviewed",
    ]


@pytest.mark.asyncio
async def test_list_reports_rejects_inverted_date_range():
    with pytest.raises(
        ObserverReportValidationError,
        match=(
            "fromDate must be on or "
            "before toDate"
        ),
    ):
        await list_observer_reports(
            db=object(),
            observer_id=42,
            from_date=date(
                2026,
                8,
                30,
            ),
            to_date=date(
                2026,
                8,
                20,
            ),
        )


@pytest.mark.asyncio
async def test_list_reports_passes_canonical_status_code_to_repository(
    monkeypatch,
):
    list_mock = AsyncMock(
        return_value=(
            [
                {
                    "report_reference":
                        "RC-0001",
                    "threat":
                        "Ghost fishing gear",
                    "area":
                        "Tioman Island",
                    "status":
                        "received",
                    "status_label":
                        "Report received",
                    "closure_label":
                        None,
                    "submitted_at":
                        NOW,
                }
            ],
            1,
        )
    )

    monkeypatch.setattr(
        report_repository,
        "list_my_reports",
        list_mock,
    )

    fake_db = object()

    response = await list_observer_reports(
        db=fake_db,
        observer_id=42,
        status_filter=(
            CaseStatus.RECEIVED
        ),
        page=1,
        page_size=20,
    )

    assert response.total == 1

    assert (
        response.items[0].report_reference
        == "RC-0001"
    )

    kwargs = (
        list_mock.await_args.kwargs
    )

    assert kwargs["db"] is fake_db
    assert kwargs["observer_id"] == 42
    assert kwargs["status_code"] == "received"
    assert kwargs["from_date"] is None
    assert kwargs["to_date"] is None
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 20


@pytest.mark.asyncio
async def test_other_observer_report_is_returned_as_not_found(
    monkeypatch,
):
    get_report_mock = AsyncMock(
        return_value=None
    )

    location_mock = AsyncMock()

    monkeypatch.setattr(
        report_repository,
        "get_my_report",
        get_report_mock,
    )

    monkeypatch.setattr(
        observer_report_service,
        "get_report_location",
        location_mock,
    )

    with pytest.raises(
        NotFoundError,
        match="Report not found",
    ):
        await get_observer_report(
            db=object(),
            observer_id=42,
            report_reference=(
                "RC-9999"
            ),
        )

    location_mock.assert_not_awaited()