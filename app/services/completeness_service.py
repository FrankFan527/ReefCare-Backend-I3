from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LocationSource
from app.repositories import (
    reference_repository,
    report_repository,
)
from app.schemas.report import (
    ReportCompletenessRequest,
)
from app.services.location_service import (
    LocationValidationError,
    normalise_observation_location,
)


RECOMMENDED_FIELDS: set[str] = {
    "estimatedDepthMetres",
}


def _build_summary(
    *,
    blocking_missing: list[str],
    blocking_issues: list[str],
    recommended_missing: list[str],
) -> str:
    """
    Build a short frontend-safe completeness summary.
    """

    blocking_count = (
        len(blocking_missing)
        + len(blocking_issues)
    )

    recommended_count = len(
        recommended_missing
    )

    if (
        blocking_count == 0
        and recommended_count == 0
    ):
        return (
            "The report has all required and "
            "recommended information."
        )

    parts: list[str] = []

    if blocking_count > 0:
        parts.append(
            f"{blocking_count} required issue"
            + (
                " remains"
                if blocking_count == 1
                else "s remain"
            )
        )

    if recommended_count > 0:
        parts.append(
            f"{recommended_count} recommended field"
            + (
                " could improve the report"
                if recommended_count == 1
                else "s could improve the report"
            )
        )

    return "; ".join(parts) + "."


async def evaluate_report_completeness(
    *,
    db: AsyncSession,
    observer_id: int,
    report_data: ReportCompletenessRequest,
) -> dict:
    """
    Evaluate whether an Iteration 2 report draft is ready
    for final submission.

    This is deterministic backend logic.

    It does not use AI and does not persist anything.

    Required:
    - threat category
    - observation time
    - description
    - dive session
    - named dive site
    - location confidence
    - at least one evidence item

    Recommended:
    - estimated depth

    Existing reference data and location rules are reused
    rather than duplicated.
    """

    blocking_missing: list[str] = []
    blocking_issues: list[str] = []
    recommended_missing: list[str] = []

    # --------------------------------------------------
    # Required scalar fields
    # --------------------------------------------------

    if report_data.threat_category_id is None:
        blocking_missing.append(
            "threatCategoryId"
        )

    if report_data.observed_at is None:
        blocking_missing.append(
            "observedAt"
        )

    if (
        report_data.description is None
        or report_data.description.strip() == ""
    ):
        blocking_missing.append(
            "description"
        )

    if report_data.dive_session_id is None:
        blocking_missing.append(
            "diveSessionId"
        )

    # --------------------------------------------------
    # Observation time validity
    # --------------------------------------------------

    if report_data.observed_at is not None:
        observed_at = report_data.observed_at

        if observed_at.tzinfo is None:
            blocking_issues.append(
                "observedAt must include a timezone"
            )

        elif observed_at > datetime.now(
            timezone.utc
        ):
            blocking_issues.append(
                "observedAt cannot be in the future"
            )

    # --------------------------------------------------
    # Evidence
    # --------------------------------------------------

    if report_data.evidence_count < 1:
        blocking_missing.append(
            "evidence"
        )

    # --------------------------------------------------
    # Recommended fields
    # --------------------------------------------------

    if (
        report_data
        .estimated_depth_metres
        is None
    ):
        recommended_missing.append(
            "estimatedDepthMetres"
        )

    # --------------------------------------------------
    # Threat reference validation
    # --------------------------------------------------

    if report_data.threat_category_id is not None:
        threat = (
            await reference_repository
            .get_selectable_threat_category(
                db=db,
                threat_category_id=(
                    report_data
                    .threat_category_id
                ),
            )
        )

        if threat is None:
            blocking_issues.append(
                "threatCategoryId is not selectable"
            )

    # --------------------------------------------------
    # Dive session / site validation
    # --------------------------------------------------

    dive_session = None

    if report_data.dive_session_id is not None:
        dive_session = (
            await report_repository
            .get_owned_dive_session(
                db,
                dive_session_id=(
                    report_data
                    .dive_session_id
                ),
                observer_id=observer_id,
            )
        )

        if dive_session is None:
            blocking_issues.append(
                "diveSessionId does not belong "
                "to the current observer"
            )

    location = report_data.location

    if location is None:
        blocking_missing.append(
            "location"
        )

    else:
        if (
            location.named_dive_site_id
            is None
        ):
            blocking_missing.append(
                "location.namedDiveSiteId"
            )

        if (
            location.location_confidence
            is None
            or location.location_confidence.strip()
            == ""
        ):
            blocking_missing.append(
                "location.locationConfidence"
            )

        if (
            dive_session is not None
            and location.named_dive_site_id
            is not None
            and location.named_dive_site_id
            != dive_session["dive_site_id"]
        ):
            blocking_issues.append(
                "location.namedDiveSiteId does not "
                "match the selected dive session"
            )

        # ----------------------------------------------
        # Reference-data checks
        # ----------------------------------------------

        if location.location_confidence:
            confidence = (
                await reference_repository
                .get_location_confidence(
                    db=db,
                    code=(
                        location
                        .location_confidence
                    ),
                )
            )

            if confidence is None:
                blocking_issues.append(
                    "location.locationConfidence "
                    "is not recognised"
                )

        if location.location_source is not None:
            source = (
                await reference_repository
                .get_location_source(
                    db=db,
                    code=(
                        location
                        .location_source
                        .value
                    ),
                )
            )

            if source is None:
                blocking_issues.append(
                    "location.locationSource "
                    "is not recognised"
                )

        # ----------------------------------------------
        # Reuse TC-407 normalisation rules when enough
        # information exists.
        # ----------------------------------------------

        if (
            location.named_dive_site_id
            is not None
            and location.location_confidence
        ):
            map_pin = location.map_pin
            coordinates = (
                location.coordinates
            )

            try:
                normalise_observation_location(
                    named_dive_site_id=(
                        location
                        .named_dive_site_id
                    ),
                    submitted_source=(
                        location.location_source
                    ),
                    submitted_confidence_code=(
                        location
                        .location_confidence
                    ),
                    map_pin_latitude=(
                        map_pin.latitude
                        if map_pin is not None
                        else None
                    ),
                    map_pin_longitude=(
                        map_pin.longitude
                        if map_pin is not None
                        else None
                    ),
                    coordinate_latitude=(
                        coordinates.latitude
                        if coordinates
                        is not None
                        else None
                    ),
                    coordinate_longitude=(
                        coordinates.longitude
                        if coordinates
                        is not None
                        else None
                    ),
                    relocation_notes=(
                        location
                        .relocation_notes
                    ),
                )

            except LocationValidationError as exc:
                blocking_issues.append(
                    str(exc)
                )

    # --------------------------------------------------
    # Result
    # --------------------------------------------------

    is_submittable = (
        len(blocking_missing) == 0
        and len(blocking_issues) == 0
    )

    return {
        "is_submittable":
            is_submittable,

        "blocking_missing":
            blocking_missing,

        "blocking_issues":
            blocking_issues,

        "recommended_missing":
            recommended_missing,

        "summary":
            _build_summary(
                blocking_missing=(
                    blocking_missing
                ),
                blocking_issues=(
                    blocking_issues
                ),
                recommended_missing=(
                    recommended_missing
                ),
            ),
    }