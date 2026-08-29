import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.repositories import report_repository
from app.repositories.location_repository import (
    get_report_location,
)


pytestmark = pytest.mark.integration


async def find_report_owner_and_other_observer(
    db,
):
    report_result = await db.execute(
        text(
            """
            SELECT
                r.report_reference,
                r.observer_id,
                r.report_location_id

            FROM report r

            JOIN app_user u
                ON u.user_id =
                   r.observer_id

            JOIN app_role role
                ON role.role_id =
                   u.role_id

            WHERE
                r.deleted_at IS NULL
                AND role.code =
                    'observer'

            ORDER BY
                r.submitted_at DESC

            LIMIT 1
            """
        )
    )

    report_row = (
        report_result
        .mappings()
        .first()
    )

    if report_row is None:
        pytest.skip(
            "No observer report exists "
            "in the configured database"
        )

    other_result = await db.execute(
        text(
            """
            SELECT
                u.user_id

            FROM app_user u

            JOIN app_role role
                ON role.role_id =
                   u.role_id

            WHERE
                role.code = 'observer'
                AND u.is_active = true
                AND u.user_id <>
                    :owner_id

            ORDER BY
                u.user_id

            LIMIT 1
            """
        ),
        {
            "owner_id":
                report_row[
                    "observer_id"
                ]
        },
    )

    other_observer_id = (
        other_result
        .scalar_one_or_none()
    )

    if other_observer_id is None:
        pytest.skip(
            "A second active observer "
            "is needed for isolation testing"
        )

    return (
        report_row,
        other_observer_id,
    )


@pytest.mark.asyncio
async def test_observer_report_detail_is_structurally_scoped():
    async with AsyncSessionLocal() as db:
        (
            report_row,
            other_observer_id,
        ) = (
            await find_report_owner_and_other_observer(
                db
            )
        )

        owner_result = (
            await report_repository
            .get_my_report(
                db=db,
                observer_id=(
                    report_row[
                        "observer_id"
                    ]
                ),
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
            )
        )

        other_result = (
            await report_repository
            .get_my_report(
                db=db,
                observer_id=(
                    other_observer_id
                ),
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
            )
        )

        assert owner_result is not None

        assert (
            owner_result[
                "report_reference"
            ]
            == report_row[
                "report_reference"
            ]
        )

        assert other_result is None


@pytest.mark.asyncio
async def test_observer_timeline_cannot_be_read_by_another_observer():
    async with AsyncSessionLocal() as db:
        (
            report_row,
            other_observer_id,
        ) = (
            await find_report_owner_and_other_observer(
                db
            )
        )

        owner_timeline = (
            await report_repository
            .get_report_timeline(
                db=db,
                observer_id=(
                    report_row[
                        "observer_id"
                    ]
                ),
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
            )
        )

        other_timeline = (
            await report_repository
            .get_report_timeline(
                db=db,
                observer_id=(
                    other_observer_id
                ),
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
            )
        )

        assert len(owner_timeline) >= 1

        assert other_timeline == []

        assert all(
            row["status_label"]
            for row in owner_timeline
        )


@pytest.mark.asyncio
async def test_precise_location_is_not_returned_to_another_observer():
    async with AsyncSessionLocal() as db:
        (
            report_row,
            other_observer_id,
        ) = (
            await find_report_owner_and_other_observer(
                db
            )
        )

        if (
            report_row[
                "report_location_id"
            ]
            is None
        ):
            pytest.skip(
                "Selected report has no "
                "report_location row"
            )

        owner_location = (
            await get_report_location(
                db=db,
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
                user_id=(
                    report_row[
                        "observer_id"
                    ]
                ),
            )
        )

        other_location = (
            await get_report_location(
                db=db,
                report_reference=(
                    report_row[
                        "report_reference"
                    ]
                ),
                user_id=(
                    other_observer_id
                ),
            )
        )

        assert owner_location is not None

        assert other_location is None