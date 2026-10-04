# ---------------------------------------------------------------------------
# Iteration 3 — E1 access-boundary regression tests.
#
# These tests verify the role boundaries wired directly on
# the route functions and the current-session validation
# rules.
#
# They intentionally do not retest E7/E9 business logic.
# ---------------------------------------------------------------------------

import inspect

import pytest
from fastapi import HTTPException

from app.api.dependencies import auth as auth_dependency
from app.api.dependencies.authorization import (
    require_coordinator,
    require_observer,
    require_system_admin,
)
from app.api.routes import (
    admin,
    follow_ups,
    planning,
    plans,
    related_incidents,
)
from app.core.enums import UserRole
from app.schemas.auth import RegistrationCreate


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _route_by_name(
    router,
    endpoint_name: str,
):
    """
    Find one route directly inside the supplied APIRouter.

    This deliberately avoids assumptions about global
    /api/v1, /admin or /coordinator prefixes.
    """

    matches = [
        route
        for route in router.routes
        if (
            getattr(
                route,
                "endpoint",
                None
            ) is not None
            and route.endpoint.__name__
            == endpoint_name
        )
    ]

    assert len(matches) == 1, (
        f"Expected exactly one route named "
        f"{endpoint_name!r}, found "
        f"{len(matches)}"
    )

    return matches[0]


def _dependency_calls(
    dependant,
) -> set:
    """
    Recursively collect dependency callables attached to
    one FastAPI route.
    """

    calls = set()

    for child in getattr(
        dependant,
        "dependencies",
        [],
    ):
        if child.call is not None:
            calls.add(
                child.call
            )

        calls.update(
            _dependency_calls(
                child
            )
        )

    return calls


def _assert_route_has_dependency(
    *,
    router,
    endpoint_name: str,
    dependency,
):
    route = _route_by_name(
        router,
        endpoint_name,
    )

    calls = _dependency_calls(
        route.dependant
    )

    assert dependency in calls, (
        f"{endpoint_name} must depend on "
        f"{dependency.__name__}"
    )


def _assert_route_has_no_role_dependency(
    *,
    router,
    endpoint_name: str,
):
    route = _route_by_name(
        router,
        endpoint_name,
    )

    calls = _dependency_calls(
        route.dependant
    )

    role_dependencies = {
        require_observer,
        require_coordinator,
        require_system_admin,
    }

    unexpected = (
        calls
        & role_dependencies
    )

    assert not unexpected, (
        f"{endpoint_name} unexpectedly has role "
        f"dependencies: "
        f"{[item.__name__ for item in unexpected]}"
    )


# ---------------------------------------------------------------------------
# E9 public planning boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_area_seasonality",
        "get_date_comparison",
        "get_site_comparison",
        "create_planning_brief",
    ],
)
def test_us91_to_us94_planning_routes_remain_public(
    endpoint_name: str,
):
    _assert_route_has_no_role_dependency(
        router=planning.router,
        endpoint_name=endpoint_name,
    )


# ---------------------------------------------------------------------------
# E9 US9.5 — saved plans are Observer-only.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "list_plans",
        "create_plan",
        "get_plan",
        "update_plan",
        "delete_plan",
    ],
)
def test_saved_plan_routes_require_observer(
    endpoint_name: str,
):
    _assert_route_has_dependency(
        router=plans.router,
        endpoint_name=endpoint_name,
        dependency=require_observer,
    )


# ---------------------------------------------------------------------------
# E7 — Coordinator-only conservation follow-up.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_monitoring_conditions",
        "get_follow_ups",
        "create_follow_up",
        "get_follow_up",
        "correct_follow_up",
        "create_monitoring_record",
    ],
)
def test_e7_routes_require_coordinator(
    endpoint_name: str,
):
    _assert_route_has_dependency(
        router=follow_ups.router,
        endpoint_name=endpoint_name,
        dependency=require_coordinator,
    )


# ---------------------------------------------------------------------------
# US5.9 Related Incidents — Coordinator-only.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_related_reports",
        "claim_and_compare",
        "compare_reports",
        "record_relationship_decision",
        "get_rejection_reasons",
    ],
)
def test_related_incident_routes_require_coordinator(
    endpoint_name: str,
):
    _assert_route_has_dependency(
        router=related_incidents.router,
        endpoint_name=endpoint_name,
        dependency=require_coordinator,
    )


# ---------------------------------------------------------------------------
# Administration — System-Administrator-only.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "get_users",
        "create_user",
        "update_user",
        "approve_coordinator",
    ],
)
def test_admin_routes_require_system_admin(
    endpoint_name: str,
):
    _assert_route_has_dependency(
        router=admin.router,
        endpoint_name=endpoint_name,
        dependency=require_system_admin,
    )


# ---------------------------------------------------------------------------
# Role dependency behaviour.
# ---------------------------------------------------------------------------


def test_observer_role_accepts_observer():
    current_user = {
        "user_id": 1,
        "role":
            UserRole.OBSERVER.value,
        "display_name":
            "Observer",
    }

    result = require_observer(
        current_user
    )

    assert result is current_user


def test_observer_role_rejects_coordinator():
    current_user = {
        "user_id": 2,
        "role":
            UserRole.CASE_COORDINATOR.value,
        "display_name":
            "Coordinator",
    }

    with pytest.raises(
        HTTPException
    ) as error:
        require_observer(
            current_user
        )

    assert (
        error.value.status_code
        == 403
    )


def test_coordinator_role_accepts_coordinator():
    current_user = {
        "user_id": 2,
        "role":
            UserRole.CASE_COORDINATOR.value,
        "display_name":
            "Coordinator",
    }

    result = require_coordinator(
        current_user
    )

    assert result is current_user


def test_coordinator_role_rejects_observer():
    current_user = {
        "user_id": 1,
        "role":
            UserRole.OBSERVER.value,
        "display_name":
            "Observer",
    }

    with pytest.raises(
        HTTPException
    ) as error:
        require_coordinator(
            current_user
        )

    assert (
        error.value.status_code
        == 403
    )


def test_coordinator_role_rejects_system_admin():
    """
    System Administrator does not automatically inherit
    conservation-case authority.
    """

    current_user = {
        "user_id": 3,
        "role":
            UserRole.SYSTEM_ADMIN.value,
        "display_name":
            "Admin",
    }

    with pytest.raises(
        HTTPException
    ) as error:
        require_coordinator(
            current_user
        )

    assert (
        error.value.status_code
        == 403
    )


def test_system_admin_role_accepts_system_admin():
    current_user = {
        "user_id": 3,
        "role":
            UserRole.SYSTEM_ADMIN.value,
        "display_name":
            "Admin",
    }

    result = require_system_admin(
        current_user
    )

    assert result is current_user


def test_system_admin_role_rejects_coordinator():
    current_user = {
        "user_id": 2,
        "role":
            UserRole.CASE_COORDINATOR.value,
        "display_name":
            "Coordinator",
    }

    with pytest.raises(
        HTTPException
    ) as error:
        require_system_admin(
            current_user
        )

    assert (
        error.value.status_code
        == 403
    )


# ---------------------------------------------------------------------------
# Session revocation / role-change behaviour.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_account_invalidates_existing_token(
    monkeypatch,
):
    def fake_decode_access_token(
        token: str,
    ):
        return {
            "sub": "12",
            "role":
                UserRole
                .CASE_COORDINATOR
                .value,
        }

    async def fake_get_user_by_id(
        db,
        user_id: int,
    ):
        assert user_id == 12

        return {
            "user_id": 12,
            "display_name":
                "Former Coordinator",
            "role_code":
                UserRole
                .CASE_COORDINATOR
                .value,
            "is_active": False,
        }

    monkeypatch.setattr(
        auth_dependency,
        "decode_access_token",
        fake_decode_access_token,
    )

    monkeypatch.setattr(
        auth_dependency,
        "get_user_by_id",
        fake_get_user_by_id,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        await auth_dependency.validate_session(
            token="still-signed-token",
            db=None,
        )

    assert (
        error.value.status_code
        == 401
    )

    assert (
        error.value.detail
        == "Authentication is no longer valid"
    )


@pytest.mark.asyncio
async def test_role_change_invalidates_existing_token(
    monkeypatch,
):
    """
    A token issued under one role must stop working after
    the canonical database role changes.
    """

    def fake_decode_access_token(
        token: str,
    ):
        return {
            "sub": "12",
            "role":
                UserRole
                .CASE_COORDINATOR
                .value,
        }

    async def fake_get_user_by_id(
        db,
        user_id: int,
    ):
        assert user_id == 12

        return {
            "user_id": 12,
            "display_name":
                "Changed User",
            "role_code":
                UserRole
                .OBSERVER
                .value,
            "is_active": True,
        }

    monkeypatch.setattr(
        auth_dependency,
        "decode_access_token",
        fake_decode_access_token,
    )

    monkeypatch.setattr(
        auth_dependency,
        "get_user_by_id",
        fake_get_user_by_id,
    )

    with pytest.raises(
        HTTPException
    ) as error:
        await auth_dependency.validate_session(
            token="old-coordinator-token",
            db=None,
        )

    assert (
        error.value.status_code
        == 401
    )

    assert (
        error.value.detail
        == "Authentication is no longer valid"
    )


@pytest.mark.asyncio
async def test_matching_database_role_keeps_session_valid(
    monkeypatch,
):
    def fake_decode_access_token(
        token: str,
    ):
        return {
            "sub": "12",
            "role":
                UserRole
                .CASE_COORDINATOR
                .value,
        }

    async def fake_get_user_by_id(
        db,
        user_id: int,
    ):
        assert user_id == 12

        return {
            "user_id": 12,
            "display_name":
                "Coordinator",
            "role_code":
                UserRole
                .CASE_COORDINATOR
                .value,
            "is_active": True,
        }

    monkeypatch.setattr(
        auth_dependency,
        "decode_access_token",
        fake_decode_access_token,
    )

    monkeypatch.setattr(
        auth_dependency,
        "get_user_by_id",
        fake_get_user_by_id,
    )

    result = (
        await auth_dependency
        .validate_session(
            token="valid-token",
            db=None,
        )
    )

    assert result == {
        "user_id": 12,
        "role":
            UserRole
            .CASE_COORDINATOR
            .value,
        "display_name":
            "Coordinator",
    }


# ---------------------------------------------------------------------------
# Self-registration privilege-escalation guard.
# ---------------------------------------------------------------------------


def test_registration_request_does_not_accept_role_field():
    """
    Public registration must not expose an application-role
    parameter.
    """

    assert (
        "role"
        not in
        RegistrationCreate.model_fields
    )


def test_authorization_dependencies_only_use_current_user():
    """
    Role checks operate on the authenticated current-user
    claims, never on a role value supplied by the request.
    """

    for dependency in (
        require_observer,
        require_coordinator,
        require_system_admin,
    ):
        parameters = (
            inspect.signature(
                dependency
            ).parameters
        )

        assert set(parameters) == {
            "current_user"
        }