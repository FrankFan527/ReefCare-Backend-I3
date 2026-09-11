# ---------------------------------------------------------------------------
# Observation location handling (TC-407 / US4).
#
# PostgreSQL already owns five canonical location_source
# codes:
#
#   named_dive_site
#   manual_map_pin
#   entered_coordinates
#   device_metadata
#   unknown
#
# This service normalises API input into those exact codes.
#
# No database access occurs here.
# ---------------------------------------------------------------------------

from decimal import Decimal

from app.core.enums import (
    LocationSource,
)


DIVE_SITE_ONLY_CONFIDENCE = (
    "dive_site_only"
)

UNSURE_CONFIDENCE = "unsure"


COORDINATE_LOCATION_SOURCES: set[
    LocationSource
] = {
    LocationSource.MANUAL_MAP_PIN,
    LocationSource.ENTERED_COORDINATES,
    LocationSource.DEVICE_METADATA,
}


NON_COORDINATE_LOCATION_SOURCES: set[
    LocationSource
] = {
    LocationSource.NAMED_DIVE_SITE,
    LocationSource.UNKNOWN,
}


CONFIDENCE_CODES_REQUIRING_COORDINATES: (
    set[str]
) = {
    "exact",
    "within_100m",
    "within_1km",
    UNSURE_CONFIDENCE,
}


CONFIDENCE_CODES_WITHOUT_COORDINATES: (
    set[str]
) = {
    DIVE_SITE_ONLY_CONFIDENCE,
}


VALID_LOCATION_CONFIDENCE_CODES: set[
    str
] = (
    CONFIDENCE_CODES_REQUIRING_COORDINATES
    | CONFIDENCE_CODES_WITHOUT_COORDINATES
)


class LocationValidationError(
    ValueError
):
    """
    Raised when submitted location provenance,
    coordinates or confidence are inconsistent.
    """


def validate_coordinates(
    latitude: float | Decimal | None,
    longitude: float | Decimal | None,
) -> None:
    """
    Validate a coordinate pair.

    Latitude and longitude must either both exist or both
    be absent.
    """

    if (
        latitude is None
        and longitude is None
    ):
        return

    if (
        latitude is None
        or longitude is None
    ):
        raise LocationValidationError(
            "latitude and longitude must be "
            "provided together"
        )

    if not -90 <= float(latitude) <= 90:
        raise LocationValidationError(
            "latitude must be between "
            "-90 and 90"
        )

    if not -180 <= float(longitude) <= 180:
        raise LocationValidationError(
            "longitude must be between "
            "-180 and 180"
        )


def resolve_location_source(
    *,
    submitted_source: (
        LocationSource | None
    ),
    has_map_pin: bool,
    has_coordinates: bool,
) -> LocationSource:
    """
    Resolve the canonical source while preserving I1
    compatibility.

    Legacy requests:
        mapPin present -> manual_map_pin
        no mapPin      -> named_dive_site

    I2 requests should send locationSource explicitly.
    """

    if submitted_source is not None:
        return submitted_source

    if has_map_pin:
        return (
            LocationSource
            .MANUAL_MAP_PIN
        )

    if has_coordinates:
        raise LocationValidationError(
            "locationSource is required when "
            "coordinates are supplied"
        )

    return (
        LocationSource.NAMED_DIVE_SITE
    )


def validate_location_source_shape(
    *,
    source: LocationSource,
    has_map_pin: bool,
    has_coordinates: bool,
) -> None:
    """
    Ensure the coordinate representation matches the
    declared provenance.
    """

    if (
        source
        == LocationSource.MANUAL_MAP_PIN
    ):
        if not has_map_pin:
            raise LocationValidationError(
                "manual_map_pin requires mapPin"
            )

        if has_coordinates:
            raise LocationValidationError(
                "manual_map_pin must not also "
                "supply coordinates"
            )

        return

    if source in {
        LocationSource.ENTERED_COORDINATES,
        LocationSource.DEVICE_METADATA,
    }:
        if not has_coordinates:
            raise LocationValidationError(
                f"{source.value} requires coordinates"
            )

        if has_map_pin:
            raise LocationValidationError(
                f"{source.value} must not also "
                "supply mapPin"
            )

        return

    if source in {
        LocationSource.NAMED_DIVE_SITE,
        LocationSource.UNKNOWN,
    }:
        if (
            has_map_pin
            or has_coordinates
        ):
            raise LocationValidationError(
                f"{source.value} must not include "
                "report-specific coordinates"
            )

        return

    raise LocationValidationError(
        "Unsupported location source"
    )


def validate_location_confidence(
    *,
    submitted_confidence_code: str | None,
    has_precise_coordinates: bool,
) -> str:
    """
    Validate confidence against whether the report has
    report-specific coordinates.

    Coordinate source:
        exact / within_100m / within_1km / unsure

    No coordinate source:
        dive_site_only
    """

    if submitted_confidence_code is None:
        if has_precise_coordinates:
            return UNSURE_CONFIDENCE

        return DIVE_SITE_ONLY_CONFIDENCE

    if (
        submitted_confidence_code
        not in VALID_LOCATION_CONFIDENCE_CODES
    ):
        raise LocationValidationError(
            "location confidence must be one of: "
            + ", ".join(
                sorted(
                    VALID_LOCATION_CONFIDENCE_CODES
                )
            )
        )

    if (
        has_precise_coordinates
        and submitted_confidence_code
        in CONFIDENCE_CODES_WITHOUT_COORDINATES
    ):
        raise LocationValidationError(
            f"Confidence "
            f"{submitted_confidence_code} "
            "cannot be used with precise coordinates"
        )

    if (
        not has_precise_coordinates
        and submitted_confidence_code
        in CONFIDENCE_CODES_REQUIRING_COORDINATES
    ):
        raise LocationValidationError(
            f"Confidence "
            f"{submitted_confidence_code} "
            "requires precise coordinates"
        )

    return submitted_confidence_code


def normalise_observation_location(
    *,
    named_dive_site_id: int,
    submitted_source: (
        LocationSource | None
    ) = None,
    submitted_confidence_code: (
        str | None
    ) = None,
    map_pin_latitude: (
        float | Decimal | None
    ) = None,
    map_pin_longitude: (
        float | Decimal | None
    ) = None,
    coordinate_latitude: (
        float | Decimal | None
    ) = None,
    coordinate_longitude: (
        float | Decimal | None
    ) = None,
    relocation_notes: (
        str | None
    ) = None,
) -> dict:
    """
    Normalise all five canonical source types into the
    arguments expected by reefcare_submit_report().

    The selected named dive site remains the general
    location for every report.
    """

    if (
        named_dive_site_id is None
        or named_dive_site_id <= 0
    ):
        raise LocationValidationError(
            "A named dive site is required "
            "for every observation"
        )

    validate_coordinates(
        latitude=map_pin_latitude,
        longitude=map_pin_longitude,
    )

    validate_coordinates(
        latitude=coordinate_latitude,
        longitude=coordinate_longitude,
    )

    has_map_pin = (
        map_pin_latitude is not None
        and map_pin_longitude is not None
    )

    has_coordinates = (
        coordinate_latitude is not None
        and coordinate_longitude is not None
    )

    source = resolve_location_source(
        submitted_source=submitted_source,
        has_map_pin=has_map_pin,
        has_coordinates=has_coordinates,
    )

    validate_location_source_shape(
        source=source,
        has_map_pin=has_map_pin,
        has_coordinates=has_coordinates,
    )

    if (
        source
        == LocationSource.MANUAL_MAP_PIN
    ):
        latitude = map_pin_latitude
        longitude = map_pin_longitude

    elif source in {
        LocationSource.ENTERED_COORDINATES,
        LocationSource.DEVICE_METADATA,
    }:
        latitude = coordinate_latitude
        longitude = coordinate_longitude

    else:
        latitude = None
        longitude = None

    has_precise_coordinates = (
        latitude is not None
        and longitude is not None
    )

    confidence_code = (
        validate_location_confidence(
            submitted_confidence_code=(
                submitted_confidence_code
            ),
            has_precise_coordinates=(
                has_precise_coordinates
            ),
        )
    )

    normalised_notes = None

    if (
        relocation_notes is not None
        and relocation_notes.strip() != ""
    ):
        normalised_notes = (
            relocation_notes.strip()
        )

    return {
        "location_source_code":
            source.value,

        "location_confidence_code":
            confidence_code,

        "latitude":
            latitude,

        "longitude":
            longitude,

        "relocation_notes":
            normalised_notes,
    }