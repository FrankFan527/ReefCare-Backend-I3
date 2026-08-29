from datetime import datetime

from app.schemas.common import APIModel


class CaseEventResponse(APIModel):
    """
    Internal trace projection for a ReefCare case.

    This is not the observer-facing timeline.
    """

    event_type: str

    from_status_code: str | None = None
    to_status_code: str | None = None

    actor_user_id: int | None = None
    actor_display_name: str | None = None

    note: str | None = None

    occurred_at: datetime