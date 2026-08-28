# ---------------------------------------------------------------------------
# Dive Session routes (US4.1).
#
# Observer-only. CurrentObserver rejects any other role with 403 before the
# handler runs, and the observer id used for the query comes from the verified
# token rather than from anything the client sends. There is no way to ask for
# somebody else's sessions.
# ---------------------------------------------------------------------------
from fastapi import APIRouter

from app.api.dependencies.authorization import CurrentObserver
from app.api.dependencies.db import DatabaseSession
from app.repositories.dive_session_repository import list_my_dive_sessions
from app.schemas.dive_session import DiveSessionResponse, DiveSiteSummary


router = APIRouter()


@router.get(
    "",
    response_model=list[DiveSessionResponse],
)
async def get_my_dive_sessions(
    current_user: CurrentObserver,
    db: DatabaseSession,
):
    """Return the signed-in observer's dive sessions for selection."""

    # the owner comes from the verified token, never from the request
    the_observer_id = current_user["user_id"]

    the_dive_session_rows = await list_my_dive_sessions(
        db=db,
        observer_id=the_observer_id,
    )

    # reshape each flat row into the nested response contract
    the_response_list = []

    for the_single_row in the_dive_session_rows:
        the_response_list.append(
            DiveSessionResponse(
                dive_session_id=the_single_row["dive_session_id"],
                label=the_single_row["label"],
                dive_date=the_single_row["dive_date"],
                named_dive_site=DiveSiteSummary(
                    dive_site_id=the_single_row["dive_site_id"],
                    name=the_single_row["dive_site_name"],
                    public_area_label=the_single_row["public_area_label"],
                ),
                approximate_start_time=the_single_row["approximate_start_time"],
                approximate_end_time=the_single_row["approximate_end_time"],
            )
        )

    return the_response_list