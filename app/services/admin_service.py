from sqlalchemy.exc import (
    IntegrityError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.exceptions import (
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
    WorkflowError,
)
from app.core.security import (
    hash_password,
)
from app.repositories.admin_repository import (
    approve_coordinator_role,
    create_managed_user,
    get_admin_user_by_email,
    get_admin_user_by_id,
    list_users,
    update_managed_user,
)


async def list_managed_users(
    db: AsyncSession,
    page: int,
    page_size: int,
):
    """
    Return the administrator account list.
    """

    try:
        return await list_users(
            db=db,
            page=page,
            page_size=page_size,
        )

    except SQLAlchemyError as exc:
        raise DatabaseOperationError(
            "Unable to load user accounts"
        ) from exc


async def create_admin_managed_user(
    db: AsyncSession,
    email: str,
    display_name: str,
    password: str,
    role_code: str,
):
    """
    Create a managed account.

    Coordinators and system administrators cannot be
    created through this generic account-creation flow.
    """

    permitted_roles = {
        UserRole.OBSERVER.value,
        UserRole.CONSERVATION_RESPONDER.value,
        UserRole.DIVE_OPERATOR.value,
    }

    if role_code not in permitted_roles:
        raise WorkflowError(
            "This role cannot be created through "
            "the managed account endpoint"
        )

    existing_user = (
        await get_admin_user_by_email(
            db=db,
            email=email,
        )
    )

    if existing_user is not None:
        raise ConflictError(
            "An account with that email already exists"
        )

    password_hash = hash_password(
        password
    )

    try:
        created = await create_managed_user(
            db=db,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role_code=role_code,
        )

        if created is None:
            await db.rollback()

            raise DatabaseOperationError(
                "The selected role is not configured"
            )

        await db.commit()

    except IntegrityError as exc:
        await db.rollback()

        raise ConflictError(
            "An account with that email already exists"
        ) from exc

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "The account could not be created"
        ) from exc

    return await get_admin_user_by_id(
        db=db,
        user_id=created["user_id"],
    )


async def update_admin_managed_user(
    db: AsyncSession,
    user_id: int,
    acting_admin_id: int,
    display_name: str | None,
    is_active: bool | None,
):
    """
    Update safe account-management fields.

    An administrator may not deactivate their own account
    through the same authenticated session.
    """

    existing = await get_admin_user_by_id(
        db=db,
        user_id=user_id,
    )

    if existing is None:
        raise NotFoundError(
            "User not found"
        )

    if (
        user_id == acting_admin_id
        and is_active is False
    ):
        raise WorkflowError(
            "You cannot deactivate your own "
            "administrator account"
        )

    try:
        await update_managed_user(
            db=db,
            user_id=user_id,
            acting_admin_id=acting_admin_id,
            display_name=display_name,
            is_active=is_active,
        )
        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "The account could not be updated"
        ) from exc

    return await get_admin_user_by_id(
        db=db,
        user_id=user_id,
    )


async def approve_case_coordinator(
    db: AsyncSession,
    user_id: int,
    acting_admin_id: int,
):
    """
    Approve persistent Case Coordinator access.

    The role is stored on app_user.role_id, so a new login
    automatically receives case_coordinator in the JWT.

    This does not bypass any case ownership checks.
    """

    existing = await get_admin_user_by_id(
        db=db,
        user_id=user_id,
    )

    if existing is None:
        raise NotFoundError(
            "User not found"
        )

    if user_id == acting_admin_id:
        raise WorkflowError(
            "An administrator cannot approve "
            "their own account as coordinator"
        )

    if (
        existing["role_code"]
        == UserRole.SYSTEM_ADMIN.value
    ):
        raise WorkflowError(
            "A system administrator cannot be "
            "converted to case coordinator"
        )

    if (
        existing["role_code"]
        == UserRole.CASE_COORDINATOR.value
    ):
        raise ConflictError(
            "The user is already a case coordinator"
        )

    if not existing["is_active"]:
        raise WorkflowError(
            "An inactive account cannot be approved "
            "as case coordinator"
        )

    try:
        updated = await approve_coordinator_role(
            db=db,
            user_id=user_id,
            acting_admin_id=acting_admin_id,
        )

        if updated is None:
            raise NotFoundError(
                "User not found"
            )

        await db.commit()

    except SQLAlchemyError as exc:
        await db.rollback()

        raise DatabaseOperationError(
            "Coordinator access could not be approved"
        ) from exc

    return await get_admin_user_by_id(
        db=db,
        user_id=user_id,
    )