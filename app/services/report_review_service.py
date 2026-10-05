from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LocationSource
from app.repositories import (
    reference_repository,
    report_repository,
)
from app.schemas.report import (
    AISuggestionState,
    ReportReviewRequest,
)
from app.services.completeness_service import (
    evaluate_report_completeness,
)
from app.services.location_service import (
    evaluate_site_distance_warning,
    get_submitted_precise_point,
)


def _normalise_ai_value(
    value: str | None,
) -> str | None:
    """
    Normalise an AI suggestion only for comparison.

    The original value is still returned to the client and
    persisted unchanged.

    Case and surrounding whitespace must not create a false
    conflict.
    """

    if value is None:
        return None

    normalised = value.strip().lower()

    if normalised == "":
        return None

    return normalised


def _build_ai_conflicts(
    suggestions: list[AISuggestionState],
) -> list[dict]:
    """
    Find disagreements between Smart Report Structuring and
    Visual Threat Recognition for the same field.

    The function is deliberately advisory:

    - it does not select a winning value
    - it does not modify suggestion status
    - it does not modify the Observer's report
    - it does not decide whether submission is allowed

    Submission readiness continues to depend on whether all
    suggestions have been explicitly resolved.

    A conflict is emitted only when both AI sources provide
    a non-empty value for the same field and those values
    differ after simple comparison normalisation.
    """

    by_field: dict[
        str,
        dict[
            str,
            AISuggestionState,
        ],
    ] = {}

    for suggestion in suggestions:
        field_suggestions = by_field.setdefault(
            suggestion.field,
            {},
        )

        field_suggestions[
            suggestion.source
        ] = suggestion

    conflicts: list[dict] = []

    for (
        field,
        field_suggestions,
    ) in by_field.items():
        text_suggestion = (
            field_suggestions.get(
                "smart_report"
            )
        )

        visual_suggestion = (
            field_suggestions.get(
                "visual_recognition"
            )
        )

        if (
            text_suggestion is None
            or visual_suggestion is None
        ):
            continue

        text_value = _normalise_ai_value(
            text_suggestion.suggested_value
        )

        visual_value = _normalise_ai_value(
            visual_suggestion.suggested_value
        )

        # An unavailable/unsure source does not create a
        # value-to-value conflict.
        if (
            text_value is None
            or visual_value is None
        ):
            continue

        if text_value == visual_value:
            continue

        conflicts.append(
            {
                "field":
                    field,

                "text_suggestion":
                    text_suggestion
                    .suggested_value,

                "visual_suggestion":
                    visual_suggestion
                    .suggested_value,

                "visual_confidence":
                    visual_suggestion
                    .confidence,
            }
        )

    return conflicts


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

    It aggregates:
    - deterministic completeness
    - selected-site/location warning
    - evidence metadata
    - AI suggestion resolution state
    - I3 text-AI versus visual-AI conflicts

    AI suggestions remain advisory. The Observer-confirmed
    report values remain canonical.
    """

    completeness = (
        await evaluate_report_completeness(
            db=db,
            observer_id=observer_id,
            report_data=report_data,
        )
    )

    # -----------------------------------------------------------------------
    # Canonical selected threat.
    # -----------------------------------------------------------------------

    threat = None

    if (
        report_data.threat_category_id
        is not None
    ):
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

    # -----------------------------------------------------------------------
    # Dive-session context.
    # -----------------------------------------------------------------------

    dive_session = None

    if (
        report_data.dive_session_id
        is not None
    ):
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

    # -----------------------------------------------------------------------
    # Selected dive site and advisory distance warning.
    # -----------------------------------------------------------------------

    dive_site = None
    location_warning = None

    location = report_data.location

    if (
        location is not None
        and
        location.named_dive_site_id
        is not None
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

            # Preserve I1 compatibility where locationSource
            # was omitted.
            if source is None:
                if (
                    location.map_pin
                    is not None
                ):
                    source = (
                        LocationSource
                        .MANUAL_MAP_PIN
                    )

                else:
                    source = (
                        LocationSource
                        .NAMED_DIVE_SITE
                    )

            map_pin = location.map_pin
            coordinates = (
                location.coordinates
            )

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

    # -----------------------------------------------------------------------
    # I3 AI final-review state.
    # -----------------------------------------------------------------------

    unresolved_suggestions = [
        suggestion
        for suggestion
        in report_data.ai_suggestions
        if (
            suggestion.status
            == "unresolved"
        )
    ]

    ai_conflicts = _build_ai_conflicts(
        report_data.ai_suggestions
    )

    ai_review = {
        "has_conflict":
            bool(ai_conflicts),

        "conflicts":
            ai_conflicts,
    }

    # -----------------------------------------------------------------------
    # Evidence review projection.
    # -----------------------------------------------------------------------

    evidence = [
        {
            "index":
                index,

            "capturedAt":
                metadata.captured_at,
        }
        for index, metadata
        in enumerate(
            report_data
            .evidence_metadata
        )
    ]

    # -----------------------------------------------------------------------
    # Final non-persistent projection.
    # -----------------------------------------------------------------------

    return {
        "is_submittable": (
            completeness[
                "is_submittable"
            ]
            and not unresolved_suggestions
        ),

        "completeness":
            completeness,

        "unresolved_suggestions":
            unresolved_suggestions,

        "ai_review":
            ai_review,

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