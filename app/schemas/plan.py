# ---------------------------------------------------------------------------
# Observer Saved Plans (US9.5).
#
# A saved plan stores planning intent only:
#
# - name
# - planning area
# - planned date
# - selected dive sites
#
# Forecast values, planning bands and AI-generated planning
# text are deliberately not persisted. They are refreshed
# when the Observer reopens the plan.
# ---------------------------------------------------------------------------

from datetime import (
    date,
    datetime,
)

from pydantic import (
    Field,
    field_validator,
)

from app.schemas.common import (
    APIModel,
)


class PlanWrite(APIModel):
    """
    Create/update payload for one Observer-owned plan.
    """

    name: str = Field(
        min_length=1,
        max_length=80,
    )

    area_code: str = Field(
        min_length=1,
        max_length=100,
    )

    planned_date: date

    dive_site_ids: list[
        int
    ] = Field(
        min_length=1,
    )

    @field_validator("name")
    @classmethod
    def validate_name(
        cls,
        value: str,
    ) -> str:
        normalised = value.strip()

        if not normalised:
            raise ValueError(
                "name must not be empty"
            )

        if len(normalised) > 80:
            raise ValueError(
                "name must be at most 80 characters"
            )

        return normalised

    @field_validator("area_code")
    @classmethod
    def normalise_area_code(
        cls,
        value: str,
    ) -> str:
        normalised = (
            value
            .strip()
            .lower()
        )

        if not normalised:
            raise ValueError(
                "areaCode must not be empty"
            )

        return normalised

    @field_validator("dive_site_ids")
    @classmethod
    def validate_site_ids(
        cls,
        value: list[int],
    ) -> list[int]:
        if not value:
            raise ValueError(
                "At least one dive site is required"
            )

        if any(
            site_id <= 0
            for site_id in value
        ):
            raise ValueError(
                "diveSiteIds must contain positive integers"
            )

        if len(value) != len(
            set(value)
        ):
            raise ValueError(
                "diveSiteIds must not contain duplicates"
            )

        return value


class SavedPlanResponse(APIModel):
    plan_id: int

    name: str

    area_code: str

    planned_date: date

    dive_site_ids: list[
        int
    ]

    created_at: datetime
    updated_at: datetime


class SavedPlanListResponse(APIModel):
    items: list[
        SavedPlanResponse
    ]