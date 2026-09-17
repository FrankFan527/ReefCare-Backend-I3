from datetime import date

from app.schemas.common import APIModel


class PublicActivityItem(APIModel):
    """
    One explicitly public-safe ReefCare activity item.

    No private report, observer, case-management or
    precise-location fields are part of this contract.
    """

    activity_id: int
    activity_type: str

    title: str
    summary: str

    activity_date: date | None = None
    source_label: str | None = None


class PublicSiteActivityResponse(APIModel):
    """
    Public-safe activity attached to one named dive site.
    """

    dive_site_id: int
    dive_site_name: str
    public_area_label: str

    has_activity: bool

    items: list[PublicActivityItem]

    message: str


class PublicReportHandoffResponse(APIModel):
    """
    Public-to-report handoff contract.

    The backend validates that the selected site exists
    and returns the canonical site id.

    Browser login/registration navigation is frontend
    state, but this contract gives the frontend a stable
    canonical value to preserve through authentication.
    """

    selected_dive_site_id: int
    selected_dive_site_name: str
    public_area_label: str

    # Published site centre, so the public map plots the real position rather
    # than a hardcoded one. Nullable because a site added later may not have
    # been sourced yet, and an absent coordinate is a truthful answer rather
    # than a gap to fill.
    centre_latitude: float | None = None
    centre_longitude: float | None = None

    # Returned with the coordinate and never without it. This is the radius a
    # dive-site-only report actually covers, and a pin drawn without it claims
    # a precision nobody supplied.
    default_uncertainty_metres: int | None = None

    requires_authentication: bool = True

    reporting_path: str = "/reports/new"

    message: str = (
        "Sign in or create an Observer account to continue "
        "reporting. Your selected dive site can be carried "
        "into the reporting workflow for confirmation."
    )