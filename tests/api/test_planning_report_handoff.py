# ---------------------------------------------------------------------------
# Epic 9 US9.6 - Saved Plan -> Report handoff integration contract.
#
# US9.6 deliberately adds no new production endpoint.
#
# Planning intent may help the frontend prefill the existing reporting flow,
# but it must never become observation evidence automatically.
#
# Contract locked by these tests:
#
# 1. The existing public site handoff remains the canonical entry point.
# 2. The handoff returns the canonical selected dive site.
# 3. The frontend reporting path is /report-a-reef.
# 4. Planning dates are not part of the report submission contract.
# 5. A future planning date cannot be submitted as observedAt.
# 6. A future planning date cannot silently become a completed dive session.
# ---------------------------------------------------------------------------

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from unittest.mock import (
    AsyncMock,
)
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import (
    TestClient,
)
from pydantic import (
    ValidationError,
)

from app.api.routes import (
    public as public_routes,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.schemas.dive_session import (
    DiveSessionCreate,
)
from app.schemas.report import (
    ReportCreate,
)


BASE_HANDOFF = (
    "/api/v1/public/dive-sites"
)


async def override_db_session():
    yield object()


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


@pytest.fixture
def client():
    app.dependency_overrides[
        get_db_session
    ] = override_db_session

    with TestClient(
        app
    ) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Existing public handoff.
# ---------------------------------------------------------------------------


def test_existing_public_handoff_accepts_planned_site(
    client,
    monkeypatch,
):
    """
    A site selected during planning may enter the existing
    reporting handoff.

    No plan-specific endpoint is required.
    """

    service_mock = AsyncMock(
        return_value={
            "selected_dive_site_id":
                23,

            "selected_dive_site_name":
                "Mini Mount",

            "public_area_label":
                "Tioman Island",

            "centre_latitude":
                2.8123,

            "centre_longitude":
                104.1602,

            "default_uncertainty_metres":
                500,

            "requires_authentication":
                True,

            "reporting_path":
                "/report-a-reef",
        }
    )

    monkeypatch.setattr(
        public_routes,
        "build_report_handoff",
        service_mock,
    )

    response = client.get(
        f"{BASE_HANDOFF}/23/report-handoff"
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert (
        body[
            "selectedDiveSiteId"
        ]
        == 23
    )

    assert (
        body[
            "selectedDiveSiteName"
        ]
        == "Mini Mount"
    )

    service_mock.assert_awaited_once()

    kwargs = (
        service_mock
        .await_args
        .kwargs
    )

    assert (
        kwargs[
            "dive_site_id"
        ]
        == 23
    )


def test_report_handoff_uses_real_frontend_reporting_path(
    client,
    monkeypatch,
):
    """
    US9.6 continues through the existing frontend report
    entry point rather than creating a planning-specific
    report path.
    """

    monkeypatch.setattr(
        public_routes,
        "build_report_handoff",
        AsyncMock(
            return_value={
                "selected_dive_site_id":
                    23,

                "selected_dive_site_name":
                    "Mini Mount",

                "public_area_label":
                    "Tioman Island",

                "centre_latitude":
                    None,

                "centre_longitude":
                    None,

                "default_uncertainty_metres":
                    500,

                "requires_authentication":
                    True,

                "reporting_path":
                    "/report-a-reef",
            }
        ),
    )

    response = client.get(
        f"{BASE_HANDOFF}/23/report-handoff"
    )

    assert (
        response.status_code
        == 200
    )

    assert (
        response.json()[
            "reportingPath"
        ]
        == "/report-a-reef"
    )


def test_handoff_is_public_and_requires_no_observer_token(
    client,
    monkeypatch,
):
    """
    Planning may begin before authentication.

    Authentication is required later by the actual Observer
    reporting endpoints, not by this public handoff.
    """

    monkeypatch.setattr(
        public_routes,
        "build_report_handoff",
        AsyncMock(
            return_value={
                "selected_dive_site_id":
                    23,

                "selected_dive_site_name":
                    "Mini Mount",

                "public_area_label":
                    "Tioman Island",

                "centre_latitude":
                    None,

                "centre_longitude":
                    None,

                "default_uncertainty_metres":
                    500,

                "requires_authentication":
                    True,

                "reporting_path":
                    "/report-a-reef",
            }
        ),
    )

    response = client.get(
        f"{BASE_HANDOFF}/23/report-handoff"
    )

    assert (
        response.status_code
        == 200
    )

    assert (
        response.json()[
            "requiresAuthentication"
        ]
        is True
    )


def test_handoff_does_not_turn_planning_date_into_report_data(
    client,
    monkeypatch,
):
    """
    The handoff contract contains the selected canonical
    site but deliberately contains no observedAt,
    diveSessionId or planning-date persistence field.
    """

    monkeypatch.setattr(
        public_routes,
        "build_report_handoff",
        AsyncMock(
            return_value={
                "selected_dive_site_id":
                    23,

                "selected_dive_site_name":
                    "Mini Mount",

                "public_area_label":
                    "Tioman Island",

                "centre_latitude":
                    None,

                "centre_longitude":
                    None,

                "default_uncertainty_metres":
                    500,

                "requires_authentication":
                    True,

                "reporting_path":
                    "/report-a-reef",
            }
        ),
    )

    response = client.get(
        f"{BASE_HANDOFF}/23/report-handoff"
    )

    assert (
        response.status_code
        == 200
    )

    body = response.json()

    assert (
        "plannedDate"
        not in body
    )

    assert (
        "observedAt"
        not in body
    )

    assert (
        "diveSessionId"
        not in body
    )

    assert (
        "planId"
        not in body
    )


# ---------------------------------------------------------------------------
# Report submission boundary.
# ---------------------------------------------------------------------------


def test_report_submission_contract_has_no_saved_plan_field():
    """
    The canonical report model stores an actual observation,
    not planning provenance.

    Saved-plan state stays in the frontend handoff layer.
    """

    assert (
        "plan_id"
        not in ReportCreate.model_fields
    )

    assert (
        "saved_plan_id"
        not in ReportCreate.model_fields
    )

    assert (
        "planned_date"
        not in ReportCreate.model_fields
    )


def test_future_planning_date_cannot_be_used_as_observed_at():
    """
    A plan may legitimately refer to a future day.

    That future day must not be silently copied into
    ReportCreate.observed_at, because observation time
    represents something that has already happened.
    """

    future_observation = (
        datetime.now(
            timezone.utc
        )
        + timedelta(
            days=1
        )
    )

    with pytest.raises(
        ValidationError,
        match=(
            "Observation time cannot be "
            "in the future"
        ),
    ):
        ReportCreate(
            threat_category_id=1,

            observed_at=(
                future_observation
            ),

            description=(
                "Observed reef damage."
            ),

            dive_session_id=1,

            location={
                "namedDiveSiteId":
                    23,

                "locationConfidence":
                    "dive_site_only",

                "locationSource":
                    "named_dive_site",
            },
        )


def test_report_model_accepts_actual_past_observation_time():
    """
    The same report contract accepts an actual observation
    timestamp after the dive has happened.
    """

    actual_observation = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            hours=1
        )
    )

    report = ReportCreate(
        threat_category_id=1,

        observed_at=(
            actual_observation
        ),

        description=(
            "Observed reef damage."
        ),

        dive_session_id=1,

        location={
            "namedDiveSiteId":
                23,

            "locationConfidence":
                "dive_site_only",

            "locationSource":
                "named_dive_site",
        },
    )

    assert (
        report.observed_at
        == actual_observation
    )

    assert (
        report.location
        .named_dive_site_id
        == 23
    )


# ---------------------------------------------------------------------------
# Dive-session boundary.
# ---------------------------------------------------------------------------


def test_future_planning_date_cannot_become_completed_dive_session():
    """
    A future saved-plan date is planning intent only.

    DiveSessionCreate independently rejects a future
    diveDate in Malaysia, preventing the handoff from
    manufacturing a completed dive before it happened.
    """

    malaysia_timezone = ZoneInfo(
        "Asia/Kuala_Lumpur"
    )

    future_dive_date = (
        datetime.now(
            malaysia_timezone
        ).date()
        + timedelta(
            days=1
        )
    )

    with pytest.raises(
        ValidationError,
        match=(
            "dive_date cannot be "
            "in the future"
        ),
    ):
        DiveSessionCreate(
            named_dive_site_id=23,

            dive_date=(
                future_dive_date
            ),
        )


def test_actual_dive_date_can_create_session_contract():
    """
    Once the planned dive has actually occurred, the
    existing Dive Session contract can carry the real site
    and real dive date into reporting.
    """

    malaysia_timezone = ZoneInfo(
        "Asia/Kuala_Lumpur"
    )

    actual_dive_date = (
        datetime.now(
            malaysia_timezone
        ).date()
    )

    session = DiveSessionCreate(
        named_dive_site_id=23,

        dive_date=(
            actual_dive_date
        ),
    )

    assert (
        session.named_dive_site_id
        == 23
    )

    assert (
        session.dive_date
        == actual_dive_date
    )


# ---------------------------------------------------------------------------
# OpenAPI boundary.
# ---------------------------------------------------------------------------


def test_openapi_keeps_existing_report_handoff_route(
    client,
):
    paths = (
        app.openapi()[
            "paths"
        ]
    )

    handoff_path = (
        "/api/v1/public/"
        "dive-sites/{dive_site_id}/"
        "report-handoff"
    )

    assert (
        handoff_path
        in paths
    )

    assert (
        "get"
        in paths[
            handoff_path
        ]
    )


def test_us96_does_not_require_new_plan_report_endpoint(
    client,
):
    """
    Lock the intended architecture:

    US9.6 reuses existing report APIs rather than adding a
    second plan-specific reporting workflow.
    """

    paths = (
        app.openapi()[
            "paths"
        ]
    )

    forbidden_paths = {
        (
            "/api/v1/plans/"
            "{plan_id}/report-context"
        ),

        (
            "/api/v1/plans/"
            "{plan_id}/report-handoff"
        ),

        (
            "/api/v1/reports/"
            "from-plan"
        ),
    }

    for path in forbidden_paths:
        assert (
            path
            not in paths
        )