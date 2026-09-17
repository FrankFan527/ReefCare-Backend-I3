from fastapi import (
    APIRouter,
    Query,
    status,
)

from app.api.dependencies.authorization import (
    CurrentSystemAdmin,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdate,
    CoordinatorApprovalResponse,
)
from app.services.admin_service import (
    approve_case_coordinator,
    create_admin_managed_user,
    list_managed_users,
    update_admin_managed_user,
)


router = APIRouter()


@router.get(
    "/users",
    response_model=AdminUserListResponse,
)
async def get_users(
    current_admin: CurrentSystemAdmin,
    db: DatabaseSession,
    page: int = Query(
        default=1,
        ge=1,
        le=10_000,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
):
    """
    List ReefCare accounts for system administration.

    Password hashes and external authentication identifiers
    are never exposed.
    """

    rows, total = await list_managed_users(
        db=db,
        page=page,
        page_size=page_size,
    )

    return AdminUserListResponse(
        items=[
            AdminUserResponse(
                id=row["user_id"],
                email=row["email"],
                display_name=row[
                    "display_name"
                ],
                role=row["role_code"],
                is_active=row[
                    "is_active"
                ],
                created_at=row[
                    "created_at"
                ],
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    the_user_input: AdminUserCreate,
    current_admin: CurrentSystemAdmin,
    db: DatabaseSession,
):
    """
    Create a managed ReefCare account.

    Coordinators require a separate approval action.
    """

    row = await create_admin_managed_user(
        db=db,
        email=str(
            the_user_input.email
        ),
        display_name=(
            the_user_input.display_name
        ),
        password=(
            the_user_input.password
        ),
        role_code=(
            the_user_input.role.value
        ),
    )

    return AdminUserResponse(
        id=row["user_id"],
        email=row["email"],
        display_name=row[
            "display_name"
        ],
        role=row["role_code"],
        is_active=row[
            "is_active"
        ],
        created_at=row[
            "created_at"
        ],
    )


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserResponse,
)
async def update_user(
    user_id: int,
    the_user_input: AdminUserUpdate,
    current_admin: CurrentSystemAdmin,
    db: DatabaseSession,
):
    """
    Update safe account-management fields.

    Role changes are intentionally excluded.
    """

    row = await update_admin_managed_user(
        db=db,
        user_id=user_id,
        acting_admin_id=current_admin[
            "user_id"
        ],
        display_name=(
            the_user_input.display_name
        ),
        is_active=(
            the_user_input.is_active
        ),
    )

    return AdminUserResponse(
        id=row["user_id"],
        email=row["email"],
        display_name=row[
            "display_name"
        ],
        role=row["role_code"],
        is_active=row[
            "is_active"
        ],
        created_at=row[
            "created_at"
        ],
    )


@router.post(
    "/users/{user_id}/approve-coordinator",
    response_model=CoordinatorApprovalResponse,
)
async def approve_coordinator(
    user_id: int,
    current_admin: CurrentSystemAdmin,
    db: DatabaseSession,
):
    """
    Approve persistent Case Coordinator access.

    This changes account role only. It does not grant case
    ownership, precise-location access or decision authority
    outside the existing coordinator workflow.
    """

    row = await approve_case_coordinator(
        db=db,
        user_id=user_id,
        acting_admin_id=current_admin[
            "user_id"
        ],
    )

    return CoordinatorApprovalResponse(
        id=row["user_id"],
        email=row["email"],
        display_name=row[
            "display_name"
        ],
        role=row["role_code"],
        is_active=row[
            "is_active"
        ],
    )