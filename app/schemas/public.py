from datetime import date

from app.schemas.common import APIModel


class PublicDiveSiteResponse(APIModel):
    """
    Public E2 projection for one named dive site.

    planning_area_code links this canonical dive_site row
    into E9. No duplicate E9 site identity is introduced.
    """

    dive_site_id: int

    name: str

    public_area_label: str

    region: str | None = None

    centre_latitude: (
        float | None
    ) = None

    centre_longitude: (
        float | None
    ) = None

    default_uncertainty_metres: (
        int | None
    ) = None

    planning_available: bool

    planning_area_code: (
        str | None
    ) = None


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

    This contract remains specifically E2 -> E4 reporting.
    E2 -> E9 planning information belongs to
    PublicDiveSiteResponse.
    """

    selected_dive_site_id: int
    selected_dive_site_name: str
    public_area_label: str

    centre_latitude: float | None = None
    centre_longitude: float | None = None

    default_uncertainty_metres: (
        int | None
    ) = None

    requires_authentication: bool = True

    reporting_path: str = (
        "/report-a-reef"
    )

    message: str = (
        "Sign in or create an Observer account to continue "
        "reporting. Your selected dive site can be carried "
        "into the reporting workflow for confirmation."
    )