# ---------------------------------------------------------------------------
# Observer Saved Plan persistence (US9.5).
#
# Ownership is enforced in SQL.
#
# A plan belonging to another Observer is therefore never
# loaded into the service layer.
# ---------------------------------------------------------------------------

from sqlalchemy import (
    bindparam,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)


async def list_saved_plans(
    db: AsyncSession,
    observer_id: int,
) -> list:
    """
    Return all plans owned by the authenticated Observer.
    """

    result = await db.execute(
        text(
            """
            SELECT
                sp.saved_plan_id
                    AS plan_id,

                sp.name,

                sp.area_code,

                sp.planned_date,

                sp.created_at,

                sp.updated_at,

                COALESCE(
                    ARRAY_AGG(
                        sps.dive_site_id
                        ORDER BY
                            sps.display_order,
                            sps.dive_site_id
                    )
                    FILTER (
                        WHERE
                            sps.dive_site_id
                            IS NOT NULL
                    ),
                    ARRAY[]::integer[]
                )
                    AS dive_site_ids

            FROM saved_plan AS sp

            LEFT JOIN saved_plan_site AS sps
                ON sps.saved_plan_id =
                   sp.saved_plan_id

            WHERE
                sp.observer_id =
                    :observer_id

            GROUP BY
                sp.saved_plan_id,
                sp.name,
                sp.area_code,
                sp.planned_date,
                sp.created_at,
                sp.updated_at

            ORDER BY
                sp.updated_at DESC,
                sp.saved_plan_id DESC
            """
        ),
        {
            "observer_id":
                observer_id,
        },
    )

    return (
        result
        .mappings()
        .all()
    )


async def get_saved_plan(
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
):
    """
    Return one plan only when it belongs to this Observer.
    """

    result = await db.execute(
        text(
            """
            SELECT
                sp.saved_plan_id
                    AS plan_id,

                sp.name,

                sp.area_code,

                sp.planned_date,

                sp.created_at,

                sp.updated_at,

                COALESCE(
                    ARRAY_AGG(
                        sps.dive_site_id
                        ORDER BY
                            sps.display_order,
                            sps.dive_site_id
                    )
                    FILTER (
                        WHERE
                            sps.dive_site_id
                            IS NOT NULL
                    ),
                    ARRAY[]::integer[]
                )
                    AS dive_site_ids

            FROM saved_plan AS sp

            LEFT JOIN saved_plan_site AS sps
                ON sps.saved_plan_id =
                   sp.saved_plan_id

            WHERE
                sp.saved_plan_id =
                    :plan_id

                AND sp.observer_id =
                    :observer_id

            GROUP BY
                sp.saved_plan_id,
                sp.name,
                sp.area_code,
                sp.planned_date,
                sp.created_at,
                sp.updated_at

            LIMIT 1
            """
        ),
        {
            "plan_id":
                plan_id,

            "observer_id":
                observer_id,
        },
    )

    return (
        result
        .mappings()
        .first()
    )


async def create_saved_plan(
    db: AsyncSession,
    observer_id: int,
    name: str,
    area_code: str,
    planned_date,
) -> int:
    """
    Create the parent plan row.

    The caller inserts selected sites and owns commit.
    """

    result = await db.execute(
        text(
            """
            INSERT INTO saved_plan
                (
                    observer_id,
                    name,
                    area_code,
                    planned_date
                )

            VALUES
                (
                    :observer_id,
                    :name,
                    :area_code,
                    :planned_date
                )

            RETURNING
                saved_plan_id
            """
        ),
        {
            "observer_id":
                observer_id,

            "name":
                name,

            "area_code":
                area_code,

            "planned_date":
                planned_date,
        },
    )

    return (
        result.scalar_one()
    )


async def replace_saved_plan_sites(
    db: AsyncSession,
    plan_id: int,
    site_ids: list[int],
) -> None:
    """
    Replace the selected-site relation for one plan.

    Called only inside the create/update transaction.
    """

    await db.execute(
        text(
            """
            DELETE FROM saved_plan_site

            WHERE
                saved_plan_id =
                    :plan_id
            """
        ),
        {
            "plan_id":
                plan_id,
        },
    )

    if not site_ids:
        return

    statement = (
        text(
            """
            INSERT INTO saved_plan_site
                (
                    saved_plan_id,
                    dive_site_id,
                    display_order
                )

            VALUES
                (
                    :plan_id,
                    :dive_site_id,
                    :display_order
                )
            """
        )
    )

    for (
        display_order,
        dive_site_id,
    ) in enumerate(
        site_ids
    ):
        await db.execute(
            statement,
            {
                "plan_id":
                    plan_id,

                "dive_site_id":
                    dive_site_id,

                "display_order":
                    display_order,
            },
        )


async def update_saved_plan(
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
    name: str,
    area_code: str,
    planned_date,
) -> int | None:
    """
    Update one plan only when it belongs to this Observer.

    Returns the plan id when updated, otherwise None.
    """

    result = await db.execute(
        text(
            """
            UPDATE saved_plan

            SET
                name =
                    :name,

                area_code =
                    :area_code,

                planned_date =
                    :planned_date,

                updated_at =
                    CURRENT_TIMESTAMP

            WHERE
                saved_plan_id =
                    :plan_id

                AND observer_id =
                    :observer_id

            RETURNING
                saved_plan_id
            """
        ),
        {
            "plan_id":
                plan_id,

            "observer_id":
                observer_id,

            "name":
                name,

            "area_code":
                area_code,

            "planned_date":
                planned_date,
        },
    )

    return (
        result.scalar_one_or_none()
    )


async def delete_saved_plan(
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
) -> bool:
    """
    Delete one owned plan.

    ON DELETE CASCADE is expected to remove saved_plan_site
    rows. The service treats false as NotFound.
    """

    result = await db.execute(
        text(
            """
            DELETE FROM saved_plan

            WHERE
                saved_plan_id =
                    :plan_id

                AND observer_id =
                    :observer_id

            RETURNING
                saved_plan_id
            """
        ),
        {
            "plan_id":
                plan_id,

            "observer_id":
                observer_id,
        },
    )

    return (
        result.scalar_one_or_none()
        is not None
    )


async def get_area_for_plan_validation(
    db: AsyncSession,
    area_code: str,
):
    """
    Resolve the canonical planning area.
    """

    result = await db.execute(
        text(
            """
            SELECT
                area_code,
                area_label

            FROM planning_area

            WHERE
                area_code =
                    :area_code

            LIMIT 1
            """
        ),
        {
            "area_code":
                area_code,
        },
    )

    return (
        result
        .mappings()
        .first()
    )


async def list_sites_for_plan_validation(
    db: AsyncSession,
    site_ids: list[int],
) -> list:
    """
    Resolve selected sites for plan validation.
    """

    if not site_ids:
        return []

    statement = (
        text(
            """
            SELECT
                dive_site_id,
                public_area_label

            FROM dive_site

            WHERE
                dive_site_id IN
                    :site_ids
            """
        )
        .bindparams(
            bindparam(
                "site_ids",
                expanding=True,
            )
        )
    )

    result = await db.execute(
        statement,
        {
            "site_ids":
                site_ids,
        },
    )

    return (
        result
        .mappings()
        .all()
    )