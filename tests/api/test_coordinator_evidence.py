from unittest.mock import (
    ANY,
    AsyncMock,
)

import pytest
from fastapi.testclient import (
    TestClient,
)

from app.api.dependencies.authorization import (
    require_coordinator,
)
from app.api.routes import (
    evidence as evidence_routes,
)
from app.db.session import (
    get_db_session,
)
from app.main import app
from app.services.evidence_service import (
    EvidenceFile,
)


async def override_db_session():
    yield object()


def override_coordinator():
    return {
        "user_id": 12,
        "role": "case_coordinator",
    }


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

    app.dependency_overrides[
        require_coordinator
    ] = override_coordinator

    with TestClient(app) as test_client:
        yield test_client


def test_owned_case_evidence_is_streamed(
    client,
    monkeypatch,
):
    service_mock = AsyncMock(
        return_value=EvidenceFile(
            content=b"fake-image-bytes",
            content_type="image/png",
        )
    )

    monkeypatch.setattr(
        evidence_routes,
        "get_case_evidence_file",
        service_mock,
    )

    response = client.get(
        (
            "/api/v1/coordinator/"
            "reports/RC-0008/"
            "evidence/15"
        )
    )

    assert response.status_code == 200

    assert (
        response.content
        == b"fake-image-bytes"
    )

    assert (
        response.headers[
            "content-type"
        ].startswith(
            "image/png"
        )
    )

    assert (
        response.headers[
            "cache-control"
        ]
        == "private, no-store"
    )

    service_mock.assert_awaited_once_with(
        db=ANY,
        report_reference="RC-0008",
        evidence_id=15,
        coordinator_id=12,
    )