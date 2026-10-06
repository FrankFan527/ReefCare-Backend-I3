# ---------------------------------------------------------------------------
# Observer Saved Plan workflow (US9.5).
#
# Services own:
#
# - validation
# - ownership-safe behaviour
# - transaction boundaries
#
# Repositories own SQL.
# ---------------------------------------------------------------------------

from sqlalchemy.exc import (
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    DatabaseOperationError,
    NotFoundError,
    RequestValidationError,
)
from app.repositories import (
    plan_repository,
)
from app.schemas.plan import (
    SavedPlanListResponse,
    SavedPlanResponse,
)


async def validate_plan_reference_data(
    *,
    db: AsyncSession,
    area_code: str,
    dive_site_ids: list[int],
) -> None:
    """
    Validate canonical area and selected sites.

    Current production schema has no explicit
    planning_area <-> dive_site FK.

    Until that shared mapping exists, area membership is
    validated using the exact public label relationship:

        planning_area.area_label
        =
        dive_site.public_area_label

    Invalid client-supplied planning references use the E9
    HTTP 422 validation contract rather than the existing
    global DomainValidationError -> HTTP 400 behaviour.
    """

    area = (
        await plan_repository
        .get_area_for_plan_validation(
            db=db,
            area_code=area_code,
        )
    )

    if area is None:
        raise RequestValidationError(
            f"Unknown planning area: {area_code}"
        )

    sites = (
        await plan_repository
        .list_sites_for_plan_validation(
            db=db,
            site_ids=dive_site_ids,
        )
    )

    if len(sites) != len(
        dive_site_ids
    ):
        returned_ids = {
            row[
                "dive_site_id"
            ]
            for row in sites
        }

        missing_ids = [
            site_id
            for site_id
            in dive_site_ids
            if site_id not in returned_ids
        ]

        raise RequestValidationError(
            "Unknown dive site id(s): "
            + ", ".join(
                str(site_id)
                for site_id
                in missing_ids
            )
        )

    expected_area_label = (
        area[
            "area_label"
        ]
    )

    invalid_sites = [
        row[
            "dive_site_id"
        ]
        for row in sites
        if (
            row[
                "public_area_label"
            ]
            != expected_area_label
        )
    ]

    if invalid_sites:
        raise RequestValidationError(
            "Selected dive site(s) do not belong "
            f"to planning area {area_code}: "
            + ", ".join(
                str(site_id)
                for site_id
                in invalid_sites
            )
        )


def build_plan_response(
    row,
) -> SavedPlanResponse:
    return SavedPlanResponse(
        plan_id=row[
            "plan_id"
        ],

        name=row[
            "name"
        ],

        area_code=row[
            "area_code"
        ],

        planned_date=row[
            "planned_date"
        ],

        dive_site_ids=list(
            row[
                "dive_site_ids"
            ]
        ),

        created_at=row[
            "created_at"
        ],

        updated_at=row[
            "updated_at"
        ],
    )


async def list_my_saved_plans(
    *,
    db: AsyncSession,
    observer_id: int,
) -> SavedPlanListResponse:
    try:
        rows = (
            await plan_repository
            .list_saved_plans(
                db=db,
                observer_id=observer_id,
            )
        )

        return SavedPlanListResponse(
            items=[
                build_plan_response(
                    row
                )
                for row in rows
            ]
        )

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to list saved plans"
        ) from exc


async def get_my_saved_plan(
    *,
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
) -> SavedPlanResponse:
    try:
        row = (
            await plan_repository
            .get_saved_plan(
                db=db,
                observer_id=observer_id,
                plan_id=plan_id,
            )
        )

        if row is None:
            raise NotFoundError(
                "Plan not found"
            )

        return build_plan_response(
            row
        )

    except NotFoundError:
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to load saved plan"
        ) from exc


async def create_my_saved_plan(
    *,
    db: AsyncSession,
    observer_id: int,
    name: str,
    area_code: str,
    planned_date,
    dive_site_ids: list[int],
) -> SavedPlanResponse:
    await validate_plan_reference_data(
        db=db,
        area_code=area_code,
        dive_site_ids=dive_site_ids,
    )

    try:
        plan_id = (
            await plan_repository
            .create_saved_plan(
                db=db,
                observer_id=observer_id,
                name=name,
                area_code=area_code,
                planned_date=planned_date,
            )
        )

        await (
            plan_repository
            .replace_saved_plan_sites(
                db=db,
                plan_id=plan_id,
                site_ids=dive_site_ids,
            )
        )

        await db.commit()

        row = (
            await plan_repository
            .get_saved_plan(
                db=db,
                observer_id=observer_id,
                plan_id=plan_id,
            )
        )

        if row is None:
            raise DatabaseOperationError(
                "Saved plan could not be reloaded"
            )

        return build_plan_response(
            row
        )

    except DatabaseOperationError:
        await db.rollback()
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to create saved plan"
        ) from exc


async def update_my_saved_plan(
    *,
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
    name: str,
    area_code: str,
    planned_date,
    dive_site_ids: list[int],
) -> SavedPlanResponse:
    """
    Replace the plan intent with the supplied complete
    representation.

    Area + selected sites are always revalidated together.
    """

    existing = (
        await plan_repository
        .get_saved_plan(
            db=db,
            observer_id=observer_id,
            plan_id=plan_id,
        )
    )

    if existing is None:
        raise NotFoundError(
            "Plan not found"
        )

    await validate_plan_reference_data(
        db=db,
        area_code=area_code,
        dive_site_ids=dive_site_ids,
    )

    try:
        updated_plan_id = (
            await plan_repository
            .update_saved_plan(
                db=db,
                observer_id=observer_id,
                plan_id=plan_id,
                name=name,
                area_code=area_code,
                planned_date=planned_date,
            )
        )

        if updated_plan_id is None:
            raise NotFoundError(
                "Plan not found"
            )

        await (
            plan_repository
            .replace_saved_plan_sites(
                db=db,
                plan_id=plan_id,
                site_ids=dive_site_ids,
            )
        )

        await db.commit()

        row = (
            await plan_repository
            .get_saved_plan(
                db=db,
                observer_id=observer_id,
                plan_id=plan_id,
            )
        )

        if row is None:
            raise DatabaseOperationError(
                "Saved plan could not be reloaded"
            )

        return build_plan_response(
            row
        )

    except NotFoundError:
        await db.rollback()
        raise

    except DatabaseOperationError:
        await db.rollback()
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to update saved plan"
        ) from exc


async def delete_my_saved_plan(
    *,
    db: AsyncSession,
    observer_id: int,
    plan_id: int,
) -> None:
    try:
        deleted = (
            await plan_repository
            .delete_saved_plan(
                db=db,
                observer_id=observer_id,
                plan_id=plan_id,
            )
        )

        if not deleted:
            raise NotFoundError(
                "Plan not found"
            )

        await db.commit()

    except NotFoundError:
        await db.rollback()
        raise

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Unable to delete saved plan"
        ) from exc