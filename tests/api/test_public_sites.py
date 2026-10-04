from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.dependencies.db import (
    get_db_session,
)
from app.main import app
from app.services import public_service


client = TestClient(app)


async def override_db():
    yield AsyncMock()


def setup_module():
    app.dependency_overrides[
        get_db_session
    ] = override_db


def teardown_module():
    app.dependency_overrides.clear()


def test_public_site_detail_requires_no_authentication(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return {
            "dive_site_id": 23,
            "name": "Mini Mount",
            "public_area_label":
                "Redang Island",
            "region": "Terengganu",
            "centre_latitude": 5.77,
            "centre_longitude": 103.03,
            "default_uncertainty_metres": 500,
            "planning_area_code": "redang",
        }

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/23"
    )

    assert response.status_code == 200


def test_public_site_detail_returns_canonical_site_identity(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return {
            "dive_site_id": 23,
            "name": "Mini Mount",
            "public_area_label":
                "Redang Island",
            "region": "Terengganu",
            "centre_latitude": 5.77,
            "centre_longitude": 103.03,
            "default_uncertainty_metres": 500,
            "planning_area_code": "redang",
        }

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/23"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["diveSiteId"] == 23
    assert body["name"] == "Mini Mount"

    assert (
        body["publicAreaLabel"]
        == "Redang Island"
    )


def test_public_site_detail_returns_planning_mapping(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return {
            "dive_site_id": 23,
            "name": "Mini Mount",
            "public_area_label":
                "Redang Island",
            "region": "Terengganu",
            "centre_latitude": 5.77,
            "centre_longitude": 103.03,
            "default_uncertainty_metres": 500,
            "planning_area_code": "redang",
        }

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/23"
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["planningAvailable"]
        is True
    )

    assert (
        body["planningAreaCode"]
        == "redang"
    )


def test_public_site_without_planning_area_is_not_guessed(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return {
            "dive_site_id": 99,
            "name": "Unmapped Reef",

            # Deliberately matches a real planning-area
            # display label.
            #
            # The API must still not infer planning
            # availability because planning_area_code is
            # the canonical relationship.
            "public_area_label":
                "Redang Island",

            "region": "Terengganu",
            "centre_latitude": 5.80,
            "centre_longitude": 103.05,
            "default_uncertainty_metres": 500,

            "planning_area_code": None,
        }

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/99"
    )

    assert response.status_code == 200

    body = response.json()

    assert (
        body["planningAvailable"]
        is False
    )

    assert (
        body["planningAreaCode"]
        is None
    )


def test_unknown_public_site_returns_404(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return None

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/999999"
    )

    assert response.status_code == 404

    assert (
        response.json()["detail"]
        == "Dive site not found"
    )


def test_public_site_contract_uses_camel_case(
    monkeypatch,
):
    async def fake_get_public_site(
        db,
        dive_site_id,
    ):
        return {
            "dive_site_id": 23,
            "name": "Mini Mount",
            "public_area_label":
                "Redang Island",
            "region": "Terengganu",
            "centre_latitude": 5.77,
            "centre_longitude": 103.03,
            "default_uncertainty_metres": 500,
            "planning_area_code": "redang",
        }

    monkeypatch.setattr(
        public_service,
        "get_public_site",
        fake_get_public_site,
    )

    response = client.get(
        "/api/v1/public/dive-sites/23"
    )

    assert response.status_code == 200

    body = response.json()

    assert "diveSiteId" in body
    assert "publicAreaLabel" in body

    assert (
        "defaultUncertaintyMetres"
        in body
    )

    assert (
        "planningAvailable"
        in body
    )

    assert (
        "planningAreaCode"
        in body
    )

    assert "dive_site_id" not in body

    assert (
        "planning_area_code"
        not in body
    )