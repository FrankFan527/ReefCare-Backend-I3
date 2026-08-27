from fastapi import APIRouter

from app.api.dependencies.auth import CurrentUserClaims


router = APIRouter()


@router.get("/me")
async def get_current_user(
    current_user: CurrentUserClaims,
):
    return {
        "userId": current_user["user_id"],
        "role": current_user["role"],
    }