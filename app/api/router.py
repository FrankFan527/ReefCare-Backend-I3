from fastapi import APIRouter

from app.api.routes import (
    auth,
    case_actions,
    coordinator,
    dive_sessions,
    evidence,
    health,
    reference,
    reports,
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
    case_actions.router,
    prefix="/coordinator",
    tags=["Case Actions"],
)

api_router.include_router(
    evidence.router,
    prefix="/coordinator",
    tags=["Evidence"],
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
    reports.router,
    prefix="/reports",
    tags=["Reports"],
)

api_router.include_router(
    health.router,
    tags=["Health"],
)