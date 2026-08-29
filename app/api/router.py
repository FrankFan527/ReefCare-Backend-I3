from fastapi import APIRouter

from app.api.routes import (
    auth,
    coordinator,
    dive_sessions,
    health,
    reference,
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
    reference.router,
    prefix="/reference",
    tags=["Reference"],
)

api_router.include_router(
    dive_sessions.router,
    prefix="/dive-sessions",
    tags=["Dive Sessions"],
)

api_router.include_router(
    health.router,
    tags=["Health"],
)
