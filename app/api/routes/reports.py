from datetime import (
    date,
    datetime,
    timezone,
)

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import (
    ValidationError,
)
from sqlalchemy.exc import (
    DBAPIError,
)

from app.api.dependencies.authorization import (
    CurrentObserver,
)
from app.api.dependencies.db import (
    DatabaseSession,
)
from app.api.dependencies.rate_limit import (
    smart_report_limiter,
)
from app.core.enums import (
    CaseStatus,
)
from app.core.exceptions import (
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories.reference_repository import (
    get_dive_site_location_reference,
)
from app.schemas.report import (
    InformationResponseAccepted,
    InformationResponseCreate,
    LocationCheckRequest,
    LocationCheckResponse,
    ObserverReportDetailResponse,
    ObserverReportListResponse,
    ObserverTimelineResponse,
    OpenInformationRequest,
    ReportCompletenessRequest,
    ReportCompletenessResponse,
    ReportCreate,
    ReportReviewRequest,
    ReportReviewResponse,
    ReportSubmittedResponse,
)
from app.schemas.smart_report import (
    SmartReportStructureRequest,
    SmartReportStructureResponse,
)
from app.services.completeness_service import (
    evaluate_report_completeness,
)
from app.services.evidence_service import (
    EvidenceStorageError,
    EvidenceTooLargeError,
    EvidenceValidationError,
)
from app.services.information_service import (
    get_open_request_for_observer,
    respond_to_information_request,
)
from app.services.location_service import (
    evaluate_site_distance_warning,
    get_submitted_precise_point,
)
from app.services.observer_report_service import (
    ObserverReportValidationError,
    get_observer_report,
    get_observer_report_timeline,
    list_observer_reports,
)
from app.services.report_review_service import (
    review_report,
)
from app.services.report_service import (
    ReportValidationError,
    submit_report as submit_report_service,
)
from app.services.smart_report_service import (
    structure_report_description,
)


router = APIRouter()


@router.post(
    "/smart-structure",
    response_model=SmartReportStructureResponse,
)
async def smart_structure_report(
    the_report_input: SmartReportStructureRequest,
    current_observer: CurrentObserver,
):
    """
    Convert an Observer-written description into optional,
    reviewable report suggestions.

    This endpoint:
    - accepts description text only
    - never receives evidence files or precise coordinates
    - never persists the description or AI output
    - returns advisory suggestions requiring confirmation
    - returns an available=false fallback when AI fails
    """

    await smart_report_limiter.check(
        key=(
            "smart-report:"
            + str(current_observer["user_id"])
        )
    )

    return await structure_report_description(
        the_report_input.description
    )


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
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load reports",
        ) from exc


@router.post(
    "/completeness-check",
    response_model=(
        ReportCompletenessResponse
    ),
)
async def check_report_completeness(
    the_report_input: (
        ReportCompletenessRequest
    ),
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Evaluate whether a report draft is ready for final
    submission.

    This endpoint:
    - does not persist anything
    - does not upload evidence
    - does not call AI
    - does not change workflow state
    """

    result = (
        await evaluate_report_completeness(
            db=db,
            observer_id=current_observer[
                "user_id"
            ],
            report_data=the_report_input,
        )
    )

    return ReportCompletenessResponse(
        **result
    )


@router.post(
    "/location-check",
    response_model=(
        LocationCheckResponse
    ),
)
async def check_report_location(
    the_location_input: (
        LocationCheckRequest
    ),
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Perform an advisory consistency check between the
    selected named dive site and a supplied precise point.

    The result is never a submission blocker.

    This endpoint:
    - does not persist data
    - does not modify coordinates
    - does not modify the selected dive site
    - does not call AI
    """

    site_reference = (
        await get_dive_site_location_reference(
            db=db,
            dive_site_id=(
                the_location_input
                .named_dive_site_id
            ),
        )
    )

    if site_reference is None:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="Dive site not found",
        )

    map_pin = (
        the_location_input.map_pin
    )

    coordinates = (
        the_location_input.coordinates
    )

    (
        submitted_latitude,
        submitted_longitude,
    ) = get_submitted_precise_point(
        source=(
            the_location_input
            .location_source
        ),

        map_pin_latitude=(
            map_pin.latitude
            if map_pin is not None
            else None
        ),

        map_pin_longitude=(
            map_pin.longitude
            if map_pin is not None
            else None
        ),

        coordinate_latitude=(
            coordinates.latitude
            if coordinates is not None
            else None
        ),

        coordinate_longitude=(
            coordinates.longitude
            if coordinates is not None
            else None
        ),
    )

    result = (
        evaluate_site_distance_warning(
            site_reference=(
                site_reference
            ),
            submitted_latitude=(
                submitted_latitude
            ),
            submitted_longitude=(
                submitted_longitude
            ),
        )
    )

    return LocationCheckResponse(
        **result
    )


@router.post(
    "/review",
    response_model=(
        ReportReviewResponse
    ),
)
async def review_report_before_submission(
    the_report_input: (
        ReportReviewRequest
    ),
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Build the final Observer-facing report review before
    submission.

    This endpoint:
    - does not persist a report
    - does not upload evidence
    - does not mutate workflow state
    - does not call AI

    It aggregates:
    - completeness
    - selected threat/site
    - location information
    - evidence metadata
    - location warning
    - unresolved AI suggestions
    """

    result = await review_report(
        db=db,
        observer_id=current_observer[
            "user_id"
        ],
        report_data=the_report_input,
    )

    return ReportReviewResponse(
        **result
    )


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
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Unable to load report timeline"
            ),
        ) from exc


@router.get(
    "/{report_reference}",
    response_model=(
        ObserverReportDetailResponse
    ),
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
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to load report",
        ) from exc


@router.post(
    "",
    response_model=ReportSubmittedResponse,
    status_code=(
        status.HTTP_201_CREATED
    ),
)
async def submit_report(
    current_observer: CurrentObserver,
    db: DatabaseSession,
    payload: str = Form(...),
    photos: list[UploadFile] = File(...),
):
    try:
        report_data = (
            ReportCreate
            .model_validate_json(
                payload
            )
        )

        result = (
            await submit_report_service(
                db=db,
                observer_id=current_observer[
                    "user_id"
                ],
                report_data=report_data,
                photos=photos,
            )
        )

        return ReportSubmittedResponse(
            **result
        )

    except ValidationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=exc.errors(),
        ) from exc

    except EvidenceTooLargeError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_413_REQUEST_ENTITY_TOO_LARGE
            ),
            detail=str(exc),
        ) from exc

    except (
        ReportValidationError,
        EvidenceValidationError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(exc),
        ) from exc

    except EvidenceStorageError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to store evidence",
        ) from exc

    except DatabaseOperationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="Unable to submit report",
        ) from exc


@router.get(
    "/{report_reference}/information-request",
    response_model=(
        OpenInformationRequest | None
    ),
)
async def get_open_information_request_for_report(
    report_reference: str,
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Return the request awaiting this observer's answer,
    or null when no request is currently open.
    """

    try:
        the_open_request = (
            await get_open_request_for_observer(
                db=db,
                report_reference=(
                    report_reference
                ),
                observer_id=(
                    current_observer[
                        "user_id"
                    ]
                ),
            )
        )

    except NotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    if the_open_request is None:
        return None

    return OpenInformationRequest(
        request_text=(
            the_open_request[
                "request_text"
            ]
        ),
        requested_at=(
            the_open_request[
                "requested_at"
            ]
        ),
    )


@router.post(
    "/{report_reference}/information-response",
    response_model=(
        InformationResponseAccepted
    ),
)
async def submit_information_response(
    report_reference: str,
    the_response_input: (
        InformationResponseCreate
    ),
    current_observer: CurrentObserver,
    db: DatabaseSession,
):
    """
    Attach the observer's response to the existing report.

    Report reference and coordinator ownership remain
    unchanged.
    """

    the_observer_id = (
        current_observer[
            "user_id"
        ]
    )

    try:
        the_result = (
            await respond_to_information_request(
                db=db,
                report_reference=(
                    report_reference
                ),
                observer_id=(
                    the_observer_id
                ),
                response_text=(
                    the_response_input
                    .response_text
                ),
            )
        )

        await db.commit()

    except DBAPIError as exc:
        await db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=(
                "The response could not be "
                "recorded for this report"
            ),
        ) from exc

    return InformationResponseAccepted(
        report_reference=(
            the_result[
                "report_reference"
            ]
        ),

        status=(
            the_result[
                "status"
            ]
        ),

        response_text=(
            the_result[
                "response_text"
            ]
        ),

        responded_at=datetime.now(
            timezone.utc
        ),

        coordinator_retained=(
            the_result[
                "coordinator_retained"
            ]
        ),
    )
