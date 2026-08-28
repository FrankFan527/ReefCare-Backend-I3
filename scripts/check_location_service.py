# ---------------------------------------------------------------------------
# Direct checks on location_service. No database, no server, no token: these
# are pure functions, so they can be exercised on their own.
#
# Each case below is one of the rules reefcare_submit_report enforces, so if
# these pass, the values handed to that function will not be rejected.
# ---------------------------------------------------------------------------
from app.services.location_service import (
    LocationValidationError,
    normalise_observation_location,
    validate_coordinates,
)


def show(the_case_name: str, the_result) -> None:
    print(f"{the_case_name}: {the_result}")


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
try:
    validate_coordinates(latitude=2.7891, longitude=None)
    print("half coordinate: NOT REJECTED - this is a bug")
except LocationValidationError as the_error:
    show("half coordinate rejected", the_error)

# 6. impossible latitude
try:
    validate_coordinates(latitude=999, longitude=104.1567)
    print("bad latitude: NOT REJECTED - this is a bug")
except LocationValidationError as the_error:
    show("bad latitude rejected", the_error)

# 7. a confidence code that is not one of the five
try:
    normalise_observation_location(
        named_dive_site_id=3,
        submitted_confidence_code="pretty_sure",
    )
    print("bad confidence: NOT REJECTED - this is a bug")
except LocationValidationError as the_error:
    show("bad confidence rejected", the_error)