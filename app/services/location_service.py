# ---------------------------------------------------------------------------
# Observation location handling (US4.1).
#
# IMPORTANT FOR CALLERS: nothing here touches the database. reefcare_submit_report()
# performs the INSERT INTO report_location itself, so this module only computes
# the values passed into that function. Pure functions, no session, no SQL.
#
# Returned keys map directly onto the function's parameters:
#   location_source_code     -> p_location_source_code
#   location_confidence_code -> p_location_confidence_code
#   latitude / longitude     -> p_latitude / p_longitude
#   relocation_notes         -> p_relocation_notes
# ---------------------------------------------------------------------------
from decimal import Decimal


# the codes seeded in 02_seed_reference.sql
LOCATION_SOURCE_NAMED_DIVE_SITE: str = "named_dive_site"
LOCATION_SOURCE_MANUAL_MAP_PIN: str = "manual_map_pin"

# the five options from US4.1 AC4
VALID_LOCATION_CONFIDENCE_CODES: set[str] = {
    "exact",
    "within_100m",
    "within_1km",
    "dive_site_only",
    "unsure",
}

# the confidence used when a report has no pin of its own
DIVE_SITE_ONLY_CONFIDENCE: str = "dive_site_only"


class LocationValidationError(ValueError):
    """Raised when a submitted location cannot be stored as given."""


def validate_coordinates(
    latitude: float | Decimal | None,
    longitude: float | Decimal | None,
) -> None:
    """
    Reject malformed or impossible map pin values.

    Latitude and longitude must arrive together. A lone coordinate is not a
    location, and report_location_coords_paired rejects it at the database
    level, so catching it here gives the observer a readable message instead.
    """

    if latitude is None and longitude is None:
        return

    if latitude is None or longitude is None:
        raise LocationValidationError(
            "latitude and longitude must be provided together"
        )

    if not -90 <= float(latitude) <= 90:
        raise LocationValidationError(
            "latitude must be between -90 and 90"
        )

    if not -180 <= float(longitude) <= 180:
        raise LocationValidationError(
            "longitude must be between -180 and 180"
        )


def derive_location_confidence(
    submitted_confidence_code: str | None,
    has_map_pin: bool,
) -> str:
    """
    Decide which confidence code to store.

    The observer's own answer wins whenever they gave one, because they were
    the person in the water. Only when they said nothing does this fall back:
    a report with no pin is dive_site_only, and a report with a pin but no
    stated confidence is treated as unsure rather than assumed accurate.
    Overstating precision is the more damaging error.
    """

    if submitted_confidence_code is not None:
        if submitted_confidence_code not in VALID_LOCATION_CONFIDENCE_CODES:
            raise LocationValidationError(
                f"Unknown location confidence code: {submitted_confidence_code}"
            )
        return submitted_confidence_code

    if not has_map_pin:
        return DIVE_SITE_ONLY_CONFIDENCE

    return "unsure"


def normalise_observation_location(
    named_dive_site_id: int,
    submitted_confidence_code: str | None = None,
    latitude: float | Decimal | None = None,
    longitude: float | Decimal | None = None,
    relocation_notes: str | None = None,
) -> dict:
    """
    Turn what the observer submitted into the arguments reefcare_submit_report expects.

    The named dive site is always the general location (US4.1 AC2). A map pin is
    an optional refinement on top of it, never a replacement.

    Two database rules are honoured here so the caller cannot trip them:
    a pin source must carry coordinates, and named_dive_site must not. When no
    pin is given, latitude and longitude are returned as None rather than
    guessed from the site centroid, because the site already provides the
    location and a fabricated point would look more precise than the truth.
    """

    if named_dive_site_id is None or named_dive_site_id <= 0:
        raise LocationValidationError(
            "A named dive site is required for every observation"
        )

    validate_coordinates(latitude=latitude, longitude=longitude)

    the_pin_was_supplied = latitude is not None and longitude is not None

    the_confidence_code = derive_location_confidence(
        submitted_confidence_code=submitted_confidence_code,
        has_map_pin=the_pin_was_supplied,
    )

    if the_pin_was_supplied:
        the_source_code = LOCATION_SOURCE_MANUAL_MAP_PIN
        the_latitude = latitude
        the_longitude = longitude
    else:
        the_source_code = LOCATION_SOURCE_NAMED_DIVE_SITE
        the_latitude = None
        the_longitude = None

    # relocation notes are often more useful to a removal team than a
    # coordinate, so blank strings are normalised away rather than stored
    the_relocation_notes = None

    if relocation_notes is not None and relocation_notes.strip() != "":
        the_relocation_notes = relocation_notes.strip()

    return {
        "location_source_code": the_source_code,
        "location_confidence_code": the_confidence_code,
        "latitude": the_latitude,
        "longitude": the_longitude,
        "relocation_notes": the_relocation_notes,
    }