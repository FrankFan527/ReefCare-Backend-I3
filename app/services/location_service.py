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

# the confidence recorded when a report has no pin of its own
DIVE_SITE_ONLY_CONFIDENCE: str = "dive_site_only"

# the confidence assumed when a pin was dropped but no accuracy was stated
UNSURE_CONFIDENCE: str = "unsure"

# Every code except dive_site_only describes a radius around a point:
# exact is 25 m, within_100m is 100 m, within_1km is 1 km, unsure is 2 km.
# Without coordinates there is no point for that radius to surround, so these
# are only meaningful alongside a map pin.
CONFIDENCE_CODES_REQUIRING_A_PIN: set[str] = {
    "exact",
    "within_100m",
    "within_1km",
    UNSURE_CONFIDENCE,
}

# dive_site_only carries no uncertainty of its own; it resolves to whichever
# default_uncertainty_metres the chosen site has. It is the only honest answer
# when the observer did not drop a pin, and it contradicts one that they did.
CONFIDENCE_CODES_WITHOUT_A_PIN: set[str] = {
    DIVE_SITE_ONLY_CONFIDENCE,
}

VALID_LOCATION_CONFIDENCE_CODES: set[str] = (
    CONFIDENCE_CODES_REQUIRING_A_PIN | CONFIDENCE_CODES_WITHOUT_A_PIN
)


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


def validate_location_confidence(
    submitted_confidence_code: str | None,
    has_map_pin: bool,
) -> str:
    """
    Validate the observer's confidence against how they gave the location.

    Replaces the earlier derive_location_confidence(...), which accepted any
    valid code regardless of whether coordinates were supplied. That allowed
    "exact" with no pin, producing a site-only location claiming 25 m accuracy
    with nothing to be accurate about. Overstating precision is the more
    damaging error here, because a coordinator reading "Exact" would trust a
    position that was never given.

    The rules:
    - no pin  -> dive_site_only only
    - a pin   -> anything except dive_site_only

    When nothing was submitted a compatible default is chosen: dive_site_only
    without a pin, unsure with one. A pin whose accuracy the observer did not
    state is treated as unsure rather than assumed accurate.
    """

    if submitted_confidence_code is None:
        if has_map_pin:
            return UNSURE_CONFIDENCE
        return DIVE_SITE_ONLY_CONFIDENCE

    if submitted_confidence_code not in VALID_LOCATION_CONFIDENCE_CODES:
        raise LocationValidationError(
            "location confidence must be one of: "
            + ", ".join(sorted(VALID_LOCATION_CONFIDENCE_CODES))
        )

    if has_map_pin and submitted_confidence_code in CONFIDENCE_CODES_WITHOUT_A_PIN:
        raise LocationValidationError(
            f"Confidence {submitted_confidence_code} cannot be used with a map "
            "pin, because it describes a location given by dive site alone"
        )

    if not has_map_pin and submitted_confidence_code in CONFIDENCE_CODES_REQUIRING_A_PIN:
        raise LocationValidationError(
            f"Confidence {submitted_confidence_code} requires coordinates; "
            f"without a map pin the only valid confidence is "
            f"{DIVE_SITE_ONLY_CONFIDENCE}"
        )

    return submitted_confidence_code


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

    the_confidence_code = validate_location_confidence(
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