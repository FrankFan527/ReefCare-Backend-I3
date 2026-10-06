from datetime import (
    date,
    datetime,
    timezone,
)
from unittest.mock import (
    AsyncMock,
)

import pytest

from app.core.exceptions import (
    NotFoundError,
    RequestValidationError,
)
from app.services import (
    plan_service as service,
)


NOW = datetime(
    2026,
    10,
    4,
    8,
    0,
    tzinfo=timezone.utc,
)


def plan_row():
    return {
        "plan_id": 12,
        "name": "Redang dive plan",
        "area_code": "redang",
        "planned_date": date(
            2026,
            10,
            10,
        ),
        "dive_site_ids": [
            21,
            23,
        ],
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.asyncio
async def test_unknown_area_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "get_area_for_plan_validation",
        AsyncMock(
            return_value=None
        ),
    )

    with pytest.raises(
        RequestValidationError,
        match="Unknown planning area",
    ) as error:
        await service.validate_plan_reference_data(
            db=object(),
            area_code="invalid",
            dive_site_ids=[
                21,
            ],
        )

    assert (
        error.value.status_code
        == 422
    )

    assert (
        error.value.error_code
        == "validation_error"
    )


@pytest.mark.asyncio
async def test_unknown_site_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "get_area_for_plan_validation",
        AsyncMock(
            return_value={
                "area_code":
                    "redang",

                "area_label":
                    "Redang Island",
            }
        ),
    )

    monkeypatch.setattr(
        service.plan_repository,
        "list_sites_for_plan_validation",
        AsyncMock(
            return_value=[
                {
                    "dive_site_id":
                        21,

                    "public_area_label":
                        "Redang Island",
                }
            ]
        ),
    )

    with pytest.raises(
        RequestValidationError,
        match="Unknown dive site",
    ) as error:
        await service.validate_plan_reference_data(
            db=object(),
            area_code="redang",
            dive_site_ids=[
                21,
                99,
            ],
        )

    assert (
        error.value.status_code
        == 422
    )

    assert (
        error.value.error_code
        == "validation_error"
    )


@pytest.mark.asyncio
async def test_site_from_another_area_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "get_area_for_plan_validation",
        AsyncMock(
            return_value={
                "area_code":
                    "redang",

                "area_label":
                    "Redang Island",
            }
        ),
    )

    monkeypatch.setattr(
        service.plan_repository,
        "list_sites_for_plan_validation",
        AsyncMock(
            return_value=[
                {
                    "dive_site_id":
                        21,

                    "public_area_label":
                        "Tioman Island",
                }
            ]
        ),
    )

    with pytest.raises(
        RequestValidationError,
        match="do not belong",
    ) as error:
        await service.validate_plan_reference_data(
            db=object(),
            area_code="redang",
            dive_site_ids=[
                21,
            ],
        )

    assert (
        error.value.status_code
        == 422
    )

    assert (
        error.value.error_code
        == "validation_error"
    )


@pytest.mark.asyncio
async def test_valid_area_and_sites_pass_validation(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "get_area_for_plan_validation",
        AsyncMock(
            return_value={
                "area_code":
                    "redang",

                "area_label":
                    "Redang Island",
            }
        ),
    )

    monkeypatch.setattr(
        service.plan_repository,
        "list_sites_for_plan_validation",
        AsyncMock(
            return_value=[
                {
                    "dive_site_id":
                        21,

                    "public_area_label":
                        "Redang Island",
                },
                {
                    "dive_site_id":
                        23,

                    "public_area_label":
                        "Redang Island",
                },
            ]
        ),
    )

    await service.validate_plan_reference_data(
        db=object(),
        area_code="redang",
        dive_site_ids=[
            21,
            23,
        ],
    )


@pytest.mark.asyncio
async def test_get_other_users_plan_behaves_as_not_found(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "get_saved_plan",
        AsyncMock(
            return_value=None
        ),
    )

    with pytest.raises(
        NotFoundError,
        match="Plan not found",
    ):
        await service.get_my_saved_plan(
            db=AsyncMock(),
            observer_id=7,
            plan_id=999,
        )


@pytest.mark.asyncio
async def test_list_returns_saved_plan_response(
    monkeypatch,
):
    monkeypatch.setattr(
        service.plan_repository,
        "list_saved_plans",
        AsyncMock(
            return_value=[
                plan_row()
            ]
        ),
    )

    result = (
        await service
        .list_my_saved_plans(
            db=AsyncMock(),
            observer_id=7,
        )
    )

    assert len(
        result.items
    ) == 1

    assert (
        result.items[0].plan_id
        == 12
    )

    assert (
        result.items[0].area_code
        == "redang"
    )

    assert (
        result.items[0].dive_site_ids
        == [21, 23]
    )


@pytest.mark.asyncio
async def test_create_uses_authenticated_observer_and_commits(
    monkeypatch,
):
    db = AsyncMock()

    monkeypatch.setattr(
        service,
        "validate_plan_reference_data",
        AsyncMock(),
    )

    create_mock = AsyncMock(
        return_value=12
    )

    replace_mock = AsyncMock()

    get_mock = AsyncMock(
        return_value=plan_row()
    )

    monkeypatch.setattr(
        service.plan_repository,
        "create_saved_plan",
        create_mock,
    )

    monkeypatch.setattr(
        service.plan_repository,
        "replace_saved_plan_sites",
        replace_mock,
    )

    monkeypatch.setattr(
        service.plan_repository,
        "get_saved_plan",
        get_mock,
    )

    result = (
        await service
        .create_my_saved_plan(
            db=db,
            observer_id=77,
            name="Redang dive plan",
            area_code="redang",
            planned_date=date(
                2026,
                10,
                10,
            ),
            dive_site_ids=[
                21,
                23,
            ],
        )
    )

    create_mock.assert_awaited_once_with(
        db=db,
        observer_id=77,
        name="Redang dive plan",
        area_code="redang",
        planned_date=date(
            2026,
            10,
            10,
        ),
    )

    replace_mock.assert_awaited_once_with(
        db=db,
        plan_id=12,
        site_ids=[
            21,
            23,
        ],
    )

    db.commit.assert_awaited_once()

    assert (
        result.plan_id
        == 12
    )


@pytest.mark.asyncio
async def test_delete_missing_plan_returns_not_found(
    monkeypatch,
):
    db = AsyncMock()

    monkeypatch.setattr(
        service.plan_repository,
        "delete_saved_plan",
        AsyncMock(
            return_value=False
        ),
    )

    with pytest.raises(
        NotFoundError,
        match="Plan not found",
    ):
        await service.delete_my_saved_plan(
            db=db,
            observer_id=77,
            plan_id=999,
        )

    db.rollback.assert_awaited_once()