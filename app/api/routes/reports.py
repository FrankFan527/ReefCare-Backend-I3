from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import ValidationError

from app.api.dependencies.authorization import (
    CurrentObserver,
)
from app.api.dependencies.db import DatabaseSession
from app.core.exceptions import (
    DatabaseOperationError,
)
from app.schemas.report import (
    ReportCreate,
    ReportSubmittedResponse,
)
from app.services.evidence_service import (
    EvidenceStorageError,
    EvidenceValidationError,
)
from app.services.report_service import (
    ReportValidationError,
    submit_report as submit_report_service,
)


router = APIRouter()


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