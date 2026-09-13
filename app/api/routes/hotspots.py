"""Independent coordinator-only analysis; all operations are read-only."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.dependencies.authorization import CurrentCoordinator
from app.api.dependencies.db import DatabaseSession
from app.schemas.hotspot import (
    HotspotAnalysisResponse, HotspotContextResponse, HotspotIntakeItem,
    HotspotOptionsResponse, HotspotQuery, HotspotReportsQuery, HotspotReportsResponse,
)
from app.services import hotspot_service as service


router = APIRouter()


def set_response_headers(response: Response, result):
    response.headers["Cache-Control"] = "private, no-store"
    if getattr(result, "state", None) == "unavailable":
        response.status_code = 503
        response.headers["Retry-After"] = "30"
    return result


@router.get("/hotspots/options", response_model=HotspotOptionsResponse,
            responses={503: {"model": HotspotOptionsResponse}})
async def options(current_coordinator: CurrentCoordinator, db: DatabaseSession, response: Response):
    return set_response_headers(response, await service.get_options(db))


@router.get("/hotspots", response_model=HotspotAnalysisResponse,
            responses={503: {"model": HotspotAnalysisResponse}})
async def analysis(
    current_coordinator: CurrentCoordinator, db: DatabaseSession, response: Response,
    filters: Annotated[HotspotQuery, Query()],
):
    """One response provides consistent site counts, breakdowns and frequency buckets."""
    return set_response_headers(response, await service.get_analysis(db, filters))


@router.get("/hotspots/reports", response_model=HotspotReportsResponse,
            responses={503: {"model": HotspotReportsResponse}})
async def reports(
    current_coordinator: CurrentCoordinator, db: DatabaseSession, response: Response,
    filters: Annotated[HotspotReportsQuery, Query()],
):
    return set_response_headers(response, await service.get_reports(db, filters, current_coordinator["user_id"]))


@router.get("/hotspots/reports/{report_reference}/intake", response_model=HotspotIntakeItem)
async def intake(
    report_reference: str, current_coordinator: CurrentCoordinator,
    db: DatabaseSession, response: Response,
):
    """Refresh permitted ownership summary before offering claim/review navigation."""
    return set_response_headers(response, await service.get_intake(db, report_reference, current_coordinator["user_id"]))


@router.get("/reports/{report_reference}/hotspot-context", response_model=HotspotContextResponse,
            responses={503: {"model": HotspotContextResponse}})
async def context(
    report_reference: str, current_coordinator: CurrentCoordinator,
    db: DatabaseSession, response: Response,
):
    """Load separately from case review so analytical failure cannot block review."""
    return set_response_headers(response, await service.get_case_context(db, report_reference, current_coordinator["user_id"]))
