# ---------------------------------------------------------------------------
# Direct checks on location_service. No database, no server, no token: these
# are pure functions, so they can be exercised on their own.
#
# Cases 8 and 9 cover the confidence/source incompatibility raised in review:
# before the fix, "exact" with no pin produced named_dive_site + exact + no
# coordinates, which claims 25 m accuracy from a site name alone.
# ---------------------------------------------------------------------------
from app.services.location_service import (
    LocationValidationError,
    normalise_observation_location,
    validate_coordinates,
    validate_location_confidence,
)


def show(the_case_name: str, the_result) -> None:
    print(f"{the_case_name}: {the_result}")


def expect_rejection(the_case_name: str, the_callable) -> None:
    """Run something that should raise, and report whether it did."""

    try:
        the_callable()
        print(f"{the_case_name}: NOT REJECTED - this is a bug")
    except LocationValidationError as the_error:
        show(f"{the_case_name} rejected", the_error)


# 1. site only, no pin -> named_dive_site with no coordinates
show(
    "site only",
    normalise_observation_location(named_dive_site_id=3),
)

# 2. site plus a pin -> manual_map_pin carrying the coordinates
show(
    "with pin",
    normalise_observation_location(
        named_dive_site_id=3,
        latitude=2.7891,
        longitude=104.1567,
        submitted_confidence_code="within_100m",
    ),
)

# 3. observer gave a pin but no confidence -> unsure, not assumed accurate
show(
    "pin, no confidence",
    normalise_observation_location(
        named_dive_site_id=3,
        latitude=2.7891,
        longitude=104.1567,
    ),
)

# 4. relocation notes survive, trimmed
show(
    "with notes",
    normalise_observation_location(
        named_dive_site_id=3,
        relocation_notes="  past the swim-through, 12m  ",
    ),
)

# 5. half a coordinate is not a location
expect_rejection(
    "half coordinate",
    lambda: validate_coordinates(latitude=2.7891, longitude=None),
)

# 6. impossible latitude
expect_rejection(
    "bad latitude",
    lambda: validate_coordinates(latitude=999, longitude=104.1567),
)

# 7. a confidence code that is not one of the five
expect_rejection(
    "bad confidence",
    lambda: normalise_observation_location(
        named_dive_site_id=3,
        submitted_confidence_code="pretty_sure",
    ),
)

# 8. THE REVIEW BUG: exact accuracy claimed with no coordinates
expect_rejection(
    "exact without a pin",
    lambda: normalise_observation_location(
        named_dive_site_id=3,
        submitted_confidence_code="exact",
    ),
)

# 9. the opposite: dive_site_only claimed alongside a pin
expect_rejection(
    "dive_site_only with a pin",
    lambda: normalise_observation_location(
        named_dive_site_id=3,
        latitude=2.7891,
        longitude=104.1567,
        submitted_confidence_code="dive_site_only",
    ),
)

# 10. within_1km with no pin is equally meaningless
expect_rejection(
    "within_1km without a pin",
    lambda: validate_location_confidence(
        submitted_confidence_code="within_1km",
        has_map_pin=False,
    ),
)