from datetime import date

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
    ObserverReportDetailResponse,
    ObserverReportListResponse,
    ObserverTimelineResponse,
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