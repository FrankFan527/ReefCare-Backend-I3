# ---------------------------------------------------------------------------
# Dive Session routes (US4.1).
#
# Observer-only. CurrentObserver rejects any other role with 403 before the
# handler runs, and the observer id used for the query comes from the verified
# token rather than from anything the client sends. There is no way to ask for
# somebody else's sessions.
# ---------------------------------------------------------------------------
from fastapi import APIRouter, HTTPException, status

from app.api.dependencies.authorization import CurrentObserver
from app.api.dependencies.db import DatabaseSession
from app.core.exceptions import NotFoundError
from app.repositories.dive_session_repository import (
    create_dive_session,
    list_my_dive_sessions,
)
from app.schemas.dive_session import (
    DiveSessionCreate,
    DiveSessionResponse,
    DiveSiteSummary,
)
from app.services.dive_session_service import (
    generate_session_label,
    validate_dive_session,
)

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

@router.post(
    "",
    response_model=DiveSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_dive_session(
    the_session_input: DiveSessionCreate,
    current_user: CurrentObserver,
    db: DatabaseSession,
):
    """Create one dive session owned by the signed-in observer."""

    # the owner comes from the verified token, never from the request body
    the_observer_id = current_user["user_id"]

    # the only check left that needs the database: does the site exist
    try:
        await validate_dive_session(
            db=db,
            named_dive_site_id=the_session_input.named_dive_site_id,
        )
    except NotFoundError as the_error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(the_error),
        )

    # name the dive only when the observer left the label blank
    the_session_label = the_session_input.label

    if the_session_label is None or the_session_label.strip() == "":
        the_session_label = await generate_session_label(
            db=db,
            observer_id=the_observer_id,
            dive_date=the_session_input.dive_date,
        )

    the_created_row = await create_dive_session(
        db=db,
        observer_id=the_observer_id,
        dive_site_id=the_session_input.named_dive_site_id,
        dive_date=the_session_input.dive_date,
        session_label=the_session_label,
        time_in=the_session_input.approximate_start_time,
        time_out=the_session_input.approximate_end_time,
    )

    # the insert only becomes permanent here
    await db.commit()

    return DiveSessionResponse(
        dive_session_id=the_created_row["dive_session_id"],
        label=the_created_row["label"],
        dive_date=the_created_row["dive_date"],
        named_dive_site=DiveSiteSummary(
            dive_site_id=the_created_row["dive_site_id"],
            name=the_created_row["dive_site_name"],
            public_area_label=the_created_row["public_area_label"],
        ),
        approximate_start_time=the_created_row["approximate_start_time"],
        approximate_end_time=the_created_row["approximate_end_time"],
    )