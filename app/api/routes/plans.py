# ---------------------------------------------------------------------------
# Observer Saved Plans (US9.5).
#
# Every endpoint requires an authenticated Observer.
#
# observer_id is derived exclusively from the verified
# session and is never accepted from request data.
# ---------------------------------------------------------------------------

from fastapi import (
    APIRouter,
    Response,
    status,
)

from app.api.dependencies.authorization import (
    CurrentObserver,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.schemas.plan import (
    PlanWrite,
    SavedPlanListResponse,
    SavedPlanResponse,
)
from app.services.plan_service import (
    create_my_saved_plan,
    delete_my_saved_plan,
    get_my_saved_plan,
    list_my_saved_plans,
    update_my_saved_plan,
)


router = APIRouter()


@router.get(
    "",
    response_model=(
        SavedPlanListResponse
    ),
)
async def list_plans(
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    return await list_my_saved_plans(
        db=db,
        observer_id=current_observer[
            "user_id"
        ],
    )


@router.post(
    "",
    response_model=(
        SavedPlanResponse
    ),
    status_code=(
        status.HTTP_201_CREATED
    ),
)
async def create_plan(
    plan_input: PlanWrite,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    return await create_my_saved_plan(
        db=db,

        observer_id=current_observer[
            "user_id"
        ],

        name=plan_input.name,

        area_code=(
            plan_input.area_code
        ),

        planned_date=(
            plan_input.planned_date
        ),

        dive_site_ids=(
            plan_input.dive_site_ids
        ),
    )


@router.get(
    "/{plan_id}",
    response_model=(
        SavedPlanResponse
    ),
)
async def get_plan(
    plan_id: int,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    return await get_my_saved_plan(
        db=db,

        observer_id=current_observer[
            "user_id"
        ],

        plan_id=plan_id,
    )


@router.patch(
    "/{plan_id}",
    response_model=(
        SavedPlanResponse
    ),
)
async def update_plan(
    plan_id: int,
    plan_input: PlanWrite,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Replace the stored planning intent.

    PATCH is retained as the public contract, but the
    frontend sends the complete current intent so area/site
    validation can always run against a coherent state.
    """

    return await update_my_saved_plan(
        db=db,

        observer_id=current_observer[
            "user_id"
        ],

        plan_id=plan_id,

        name=plan_input.name,

        area_code=(
            plan_input.area_code
        ),

        planned_date=(
            plan_input.planned_date
        ),

        dive_site_ids=(
            plan_input.dive_site_ids
        ),
    )


@router.delete(
    "/{plan_id}",
    status_code=(
        status.HTTP_204_NO_CONTENT
    ),
)
async def delete_plan(
    plan_id: int,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    await delete_my_saved_plan(
        db=db,

        observer_id=current_observer[
            "user_id"
        ],

        plan_id=plan_id,
    )

    return Response(
        status_code=(
            status.HTTP_204_NO_CONTENT
        )
    )