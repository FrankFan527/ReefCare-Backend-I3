from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    case_actions,
    coordinator,
    dive_sessions,
    evidence,
    external_context,
    follow_ups,
    health,
    hotspots,
    planning,
    plans,
    public,
    public_context,
    reference,
    related_incidents,
    reports,
    site_history,
)


api_router = APIRouter()


api_router.include_router(
    hotspots.router,
    prefix="/coordinator",
    tags=["Geographic Reporting Hotspots"],
)


api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"],
)


api_router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Administration"],
)

api_router.include_router(
    public_context.router,
    prefix="/public",
    tags=["Public Reef Information"],
)

api_router.include_router(
    external_context.router,
    prefix="/public",
    tags=["Public Reef Information"],
)


api_router.include_router(
    public.router,
    prefix="/public",
    tags=["Public Reef Information"],
)


# ---------------------------------------------------------------------------
# Epic 9 public Reef-Aware Dive Planning.
# ---------------------------------------------------------------------------

api_router.include_router(
    planning.router,
    prefix="/public/planning",
    tags=["Reef-Aware Dive Planning"],
)


# ---------------------------------------------------------------------------
# Epic 9 authenticated Observer Saved Plans.
# ---------------------------------------------------------------------------

api_router.include_router(
    plans.router,
    prefix="/plans",
    tags=["Saved Dive Plans"],
)


api_router.include_router(
    coordinator.router,
    prefix="/coordinator",
    tags=["Coordinator"],
)


api_router.include_router(
    related_incidents.router,
    prefix="/coordinator",
    tags=["Related Incidents"],
)


api_router.include_router(
    site_history.router,
    prefix="/coordinator",
    tags=["Site History"],
)


api_router.include_router(
    follow_ups.router,
    prefix="/coordinator",
    tags=["Conservation Follow-up"],
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