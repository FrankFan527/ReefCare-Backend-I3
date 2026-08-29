# ---------------------------------------------------------------------------
# Dive Session routes (US4.1).
#
# Thin HTTP adapters. The service owns validation, labelling and the
# transaction boundary; this layer only maps domain exceptions onto status
# codes and reshapes rows into the response contract.
#
# Observer-only. CurrentObserver rejects any other role with 403 before the
# handler runs, and the observer id comes from the verified token rather than
# from anything the client sends. There is no way to ask for somebody else's
# sessions.
# ---------------------------------------------------------------------------
from fastapi import APIRouter, HTTPException, status

from app.api.dependencies.authorization import CurrentObserver
from app.api.dependencies.db import DatabaseSession
from app.core.exceptions import DatabaseOperationError, NotFoundError
from app.schemas.dive_session import (
    DiveSessionCreate,
    DiveSessionResponse,
    DiveSiteSummary,
)
from app.services.dive_session_service import (
    create_my_dive_session,
    get_my_dive_sessions,
)


router = APIRouter()


def build_dive_session_response(the_single_row) -> DiveSessionResponse:
    """
    Reshape one flat repository row into the nested response contract.

    The query returns dive site columns alongside the session columns, but the
    contract nests them under namedDiveSite. Keeping this in one function
    means the list and create endpoints cannot drift apart.
    """

    return DiveSessionResponse(
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


@router.get(
    "",
    response_model=list[DiveSessionResponse],
)
async def list_dive_sessions(
    current_user: CurrentObserver,
    db: DatabaseSession,
):
    """Return the signed-in observer's dive sessions for selection."""

    # the owner comes from the verified token, never from the request
    the_observer_id = current_user["user_id"]

    the_dive_session_rows = await get_my_dive_sessions(
        db=db,
        observer_id=the_observer_id,
    )

    return [
        build_dive_session_response(the_single_row)
        for the_single_row in the_dive_session_rows
    ]


@router.post(
    "",
    response_model=DiveSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dive_session_endpoint(
    the_session_input: DiveSessionCreate,
    current_user: CurrentObserver,
    db: DatabaseSession,
):
    """Create one dive session owned by the signed-in observer."""

    # the owner comes from the verified token, never from the request body
    the_observer_id = current_user["user_id"]

    try:
        the_created_row = await create_my_dive_session(
            db=db,
            observer_id=the_observer_id,
            named_dive_site_id=the_session_input.named_dive_site_id,
            dive_date=the_session_input.dive_date,
            label=the_session_input.label,
            approximate_start_time=the_session_input.approximate_start_time,
            approximate_end_time=the_session_input.approximate_end_time,
        )

    except NotFoundError as the_error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(the_error),
        )

    except DatabaseOperationError as the_error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(the_error),
        )

    return build_dive_session_response(the_created_row)