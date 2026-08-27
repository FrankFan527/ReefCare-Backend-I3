from fastapi import APIRouter

from app.api.routes import (
    auth,
    coordinator,
    health,
)


api_router = APIRouter()


api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"],
)


api_router.include_router(
    coordinator.router,
    prefix="/coordinator",
    tags=["Coordinator"],
)


api_router.include_router(
    health.router,
    tags=["Health"],
)