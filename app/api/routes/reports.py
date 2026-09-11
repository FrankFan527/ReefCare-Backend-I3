from datetime import date, datetime, timezone

from sqlalchemy.exc import DBAPIError

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import ValidationError

from app.api.dependencies.authorization import (
    CurrentObserver,
)
from app.api.dependencies.db import DatabaseSession
from app.core.enums import CaseStatus
from app.core.exceptions import (
    DatabaseOperationError,
    NotFoundError,
)
from app.schemas.report import (
    ReportCreate,
    ReportSubmittedResponse,
    InformationResponseAccepted,
    InformationResponseCreate,
    ObserverReportDetailResponse,
    ObserverReportListResponse,
    ObserverTimelineResponse,
    OpenInformationRequest,
)
from app.services.information_service import (
    get_open_request_for_observer,
    respond_to_information_request,
)

from app.services.evidence_service import (
    EvidenceStorageError,
    EvidenceTooLargeError,
    EvidenceValidationError,
)
from app.services.observer_report_service import (
    ObserverReportValidationError,
    get_observer_report,
    get_observer_report_timeline,
    list_observer_reports,
)
from app.services.report_service import (
    ReportValidationError,
    submit_report as submit_report_service,
)


router = APIRouter()


@router.get(
    "/mine",
    response_model=ObserverReportListResponse,
)
async def get_my_reports(
    current_observer: CurrentObserver,
    db: DatabaseSession,
    case_status: CaseStatus | None = Query(
        default=None,
        alias="status",
    ),
    from_date: date | None = Query(
        default=None,
        alias="fromDate",
    ),
    to_date: date | None = Query(
        default=None,
        alias="toDate",
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
        alias="pageSize",
    ),
):
    try:
        return await list_observer_reports(
            db=db,
            observer_id=current_observer[
                "user_id"
            ],
            status_filter=case_status,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
        )

    except ObserverReportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load reports",
        ) from exc


@router.get(
    "/{report_reference}/timeline",
    response_model=ObserverTimelineResponse,
)
async def get_report_timeline(
    report_reference: str,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    try:
        return await get_observer_report_timeline(
            db=db,
            observer_id=current_observer[
                "user_id"
            ],
            report_reference=report_reference,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load report timeline",
        ) from exc


@router.get(
    "/{report_reference}",
    response_model=ObserverReportDetailResponse,
)
async def get_my_report(
    report_reference: str,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    try:
        return await get_observer_report(
            db=db,
            observer_id=current_observer[
                "user_id"
            ],
            report_reference=report_reference,
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load report",
        ) from exc

    
@router.post(
    "",
    response_model=ReportSubmittedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_report(
    current_observer: CurrentObserver,
    db: DatabaseSession,
    payload: str = Form(...),
    photos: list[UploadFile] = File(...),
):
    try:
        report_data = (
            ReportCreate.model_validate_json(
                payload
            )
        )

        result = await submit_report_service(
            db=db,
            observer_id=current_observer[
                "user_id"
            ],
            report_data=report_data,
            photos=photos,
        )

        return ReportSubmittedResponse(
            **result
        )

    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    except EvidenceTooLargeError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            ),
            detail=str(exc),
        ) from exc

    except (
        ReportValidationError,
        EvidenceValidationError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except EvidenceStorageError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to store evidence",
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to submit report",
        ) from exc






@router.get(
    "/{report_reference}/information-request",
    response_model=OpenInformationRequest | None,
)
async def get_open_information_request_for_report(
    report_reference: str,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Return the request awaiting this observer's answer, or null if none.

    Null rather than 404 when nothing is open. A report with no outstanding
    question is a normal state, not a missing resource, and returning 404
    would make the frontend treat it as an error.
    """

    try:
        the_open_request = await get_open_request_for_observer(
            db=db,
            report_reference=report_reference,
            observer_id=current_observer["user_id"],
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if the_open_request is None:
        return None

    return OpenInformationRequest(
        request_text=the_open_request["request_text"],
        requested_at=the_open_request["requested_at"],
    )


@router.post(
    "/{report_reference}/information-response",
    response_model=InformationResponseAccepted,
)
async def submit_information_response(
    report_reference: str,
    the_response_input: InformationResponseCreate,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Attach the observer's answer to the existing case.

    The commit sits inside the try because the status move can be refused by
    reefcare_guard_status_change() at execute time, and returning 200 for a
    response that was rolled back would tell the observer their answer had
    been delivered when it had not.
    """

    # the actor comes from the verified token, never from the request
    the_observer_id = current_observer["user_id"]

    try:
        the_result = await respond_to_information_request(
            db=db,
            report_reference=report_reference,
            observer_id=the_observer_id,
            response_text=the_response_input.response_text,
        )

        await db.commit()

    except DBAPIError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The response could not be recorded for this report",
        ) from exc

    return InformationResponseAccepted(
        report_reference=the_result["report_reference"],
        status=the_result["status"],
        response_text=the_result["response_text"],
        responded_at=datetime.now(timezone.utc),
        coordinator_retained=the_result["coordinator_retained"],
    )