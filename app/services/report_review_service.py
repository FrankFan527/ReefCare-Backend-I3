from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    reference_repository,
    report_repository,
)
from app.schemas.report import (
    ReportReviewRequest,
)
from app.services.completeness_service import (
    evaluate_report_completeness,
)
from app.services.location_service import (
    evaluate_site_distance_warning,
    get_submitted_precise_point,
)


async def review_report(
    *,
    db: AsyncSession,
    observer_id: int,
    report_data: ReportReviewRequest,
) -> dict:
    """
    Build the final Observer review projection.

    This operation:
    - does not persist anything
    - does not upload evidence
    - does not mutate workflow state
    - does not call AI

    It aggregates deterministic completeness, location
    warning and the Observer-confirmation state of any AI
    suggestions.
    """

    completeness = (
        await evaluate_report_completeness(
            db=db,
            observer_id=observer_id,
            report_data=report_data,
        )
    )

    threat = None

    if report_data.threat_category_id is not None:
        threat_row = (
            await reference_repository
            .get_selectable_threat_category(
                db=db,
                threat_category_id=(
                    report_data
                    .threat_category_id
                ),
            )
        )

        if threat_row is not None:
            threat = {
                "id":
                    threat_row[
                        "threat_category_id"
                    ],

                "code":
                    threat_row["code"],

                "label":
                    threat_row["label"],
            }

    dive_session = None
    dive_site = None

    if report_data.dive_session_id is not None:
        session_row = (
            await report_repository
            .get_owned_dive_session(
                db=db,
                dive_session_id=(
                    report_data
                    .dive_session_id
                ),
                observer_id=observer_id,
            )
        )

        if session_row is not None:
            dive_session = {
                "id":
                    session_row[
                        "dive_session_id"
                    ]
            }

    location_warning = None

    location = report_data.location

    if (
        location is not None
        and location.named_dive_site_id is not None
    ):
        site_reference = (
            await reference_repository
            .get_dive_site_location_reference(
                db=db,
                dive_site_id=(
                    location
                    .named_dive_site_id
                ),
            )
        )

        if site_reference is not None:
            dive_site = {
                "id":
                    site_reference[
                        "dive_site_id"
                    ],

                "name":
                    site_reference[
                        "name"
                    ],

                "generalLocation":
                    site_reference[
                        "public_area_label"
                    ],
            }

            source = (
                location.location_source
            )

            if source is None:
                if location.map_pin is not None:
                    from app.core.enums import LocationSource

                    source = (
                        LocationSource
                        .MANUAL_MAP_PIN
                    )
                else:
                    from app.core.enums import LocationSource

                    source = (
                        LocationSource
                        .NAMED_DIVE_SITE
                    )

            map_pin = location.map_pin
            coordinates = location.coordinates

            (
                submitted_latitude,
                submitted_longitude,
            ) = get_submitted_precise_point(
                source=source,

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
                    if coordinates is not None
                    else None
                ),

                coordinate_longitude=(
                    coordinates.longitude
                    if coordinates is not None
                    else None
                ),
            )

            location_warning = (
                evaluate_site_distance_warning(
                    site_reference=(
                        site_reference
                    ),
                    submitted_latitude=(
                        submitted_latitude
                    ),
                    submitted_longitude=(
                        submitted_longitude
                    ),
                )
            )

    unresolved_suggestions = [
        suggestion
        for suggestion
        in report_data.ai_suggestions
        if suggestion.status == "unresolved"
    ]

    evidence = [
        {
            "index": index,
            "capturedAt":
                metadata.captured_at,
        }
        for index, metadata
        in enumerate(
            report_data.evidence_metadata
        )
    ]

    return {
        "is_submittable": (
            completeness["is_submittable"]
            and not unresolved_suggestions
        ),

        "completeness":
            completeness,

        "unresolved_suggestions":
            unresolved_suggestions,

        "report": {
            "threat":
                threat,

            "observed_at":
                report_data.observed_at,

            "estimated_depth_metres":
                report_data
                .estimated_depth_metres,

            "description":
                report_data.description,

            "dive_session":
                dive_session,

            "dive_site":
                dive_site,

            "location_source": (
                location.location_source
                if location is not None
                else None
            ),

            "location_confidence": (
                location.location_confidence
                if location is not None
                else None
            ),
        },

        "evidence":
            evidence,

        "location_warning":
            location_warning,
    }