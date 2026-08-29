from typing import Any

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DatabaseOperationError,
)
from app.repositories import (
    reference_repository,
    report_repository,
)
from app.schemas.report import ReportCreate
from app.services.evidence_service import (
    EvidenceStorageError,
    EvidenceValidationError,
    StoredEvidence,
    cleanup_private_evidence,
    prepare_evidence_metadata,
    store_private_evidence,
    validate_photo,
)


class ReportValidationError(ValueError):
    """
    Raised when report input is valid JSON/Pydantic data
    but violates an application/reference-data rule.
    """


def _derive_location_values(
    report_data: ReportCreate,
) -> tuple[
    str,
    float | None,
    float | None,
]:
    """
    Determine the canonical location_source.code and coordinates.

    Iteration 1 behaviour:

    map pin supplied:
        manual_map_pin
        latitude/longitude supplied

    no map pin:
        named_dive_site
        no report-specific coordinates

    PostgreSQL performs the final validation again.
    """

    map_pin = (
        report_data.location.map_pin
    )

    if map_pin is None:
        return (
            "named_dive_site",
            None,
            None,
        )

    return (
        "manual_map_pin",
        map_pin.latitude,
        map_pin.longitude,
    )


async def _validate_reference_data(
    *,
    db: AsyncSession,
    report_data: ReportCreate,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
]:
    """
    Resolve API input to canonical PostgreSQL reference codes.

    Returns:
        (
            threat_category,
            location_confidence,
            location_source_code,
        )

    Raises:
        ReportValidationError
    """

    threat_category = (
        await reference_repository
        .get_selectable_threat_category(
            db=db,
            threat_category_id=(
                report_data
                .threat_category_id
            ),
        )
    )

    if threat_category is None:
        raise ReportValidationError(
            "Unknown or unselectable "
            "threat category"
        )

    location_confidence = (
        await reference_repository
        .get_location_confidence(
            db=db,
            code=(
                report_data
                .location
                .location_confidence
            ),
        )
    )

    if location_confidence is None:
        raise ReportValidationError(
            "Unknown location confidence"
        )

    (
        location_source_code,
        _,
        _,
    ) = _derive_location_values(
        report_data
    )

    location_source = (
        await reference_repository
        .get_location_source(
            db=db,
            code=location_source_code,
        )
    )

    if location_source is None:
        # This should normally indicate bad/missing
        # reference seed data rather than user input.
        raise ReportValidationError(
            "Configured location source "
            "is not available"
        )

    return (
        dict(threat_category),
        dict(location_confidence),
        location_source_code,
    )


async def _store_evidence_files(
    photos: list[UploadFile],
) -> tuple[
    list[StoredEvidence],
    list[dict[str, Any]],
]:
    """
    Validate and privately store every uploaded photo.

    Returns both:
    - stored objects, used for rollback cleanup
    - JSONB-compatible metadata for PostgreSQL

    Raises:
        EvidenceValidationError
        EvidenceStorageError
    """

    if not photos:
        raise EvidenceValidationError(
            "At least one photograph "
            "is required"
        )

    stored_files: list[
        StoredEvidence
    ] = []

    evidence_items: list[
        dict[str, Any]
    ] = []

    try:
        for photo in photos:
            content = await validate_photo(
                photo
            )

            stored_file = (
                await store_private_evidence(
                    photo=photo,
                    content=content,
                )
            )

            stored_files.append(
                stored_file
            )

            evidence_items.append(
                prepare_evidence_metadata(
                    stored_file=stored_file,
                    captured_at=None,
                )
            )

        return (
            stored_files,
            evidence_items,
        )

    except (
        EvidenceValidationError,
        EvidenceStorageError,
    ):
        await cleanup_private_evidence(
            stored_files
        )

        raise


async def submit_report(
    *,
    db: AsyncSession,
    observer_id: int,
    report_data: ReportCreate,
    photos: list[UploadFile],
) -> dict[str, Any]:
    """
    Submit a complete Iteration 1 observation report.

    Application responsibilities:
    1. Require at least one valid photo.
    2. Resolve canonical threat-category code.
    3. Resolve canonical location-confidence code.
    4. Derive location-source code.
    5. Store evidence privately.
    6. Construct the evidence JSONB payload.
    7. Call report_repository.submit_report().
    8. Read the resulting confirmation.
    9. Commit the request transaction.
    10. Remove stored evidence if submission fails.

    PostgreSQL responsibilities:
    - validate the final submission
    - create report_location
    - create report
    - create evidence rows
    - generate report_reference
    - set Received status
    - create submitted event
    - create automatic intake/status event
    """

    if observer_id <= 0:
        raise ReportValidationError(
            "Invalid observer"
        )

    if not photos:
        raise EvidenceValidationError(
            "At least one photograph "
            "is required"
        )

    stored_files: list[
        StoredEvidence
    ] = []

    try:
        # Resolve canonical DB reference values before storing files.
        # This avoids unnecessary file writes for obviously invalid requests.

        (
            threat_category,
            location_confidence,
            location_source_code,
        ) = await _validate_reference_data(
            db=db,
            report_data=report_data,
        )

        (
            _,
            latitude,
            longitude,
        ) = _derive_location_values(
            report_data
        )

        dive_session = await report_repository.get_owned_dive_session(
            db,
            dive_session_id=report_data.dive_session_id,
            observer_id=observer_id,
        )

        if dive_session is None:
            raise ReportValidationError(
                "Dive session does not belong to the current observer"
            )

        if (
            report_data.location.named_dive_site_id
            is not None
            and report_data.location.named_dive_site_id
            != dive_session["dive_site_id"]
        ):
            raise ReportValidationError(
                "Dive site does not match the selected dive session"
            )

        # Validate and privately store evidence.
        (
            stored_files,
            evidence_items,
        ) = await _store_evidence_files(
            photos
        )

        # Atomic database submission.
        # The repository calls reefcare_submit_report(...).
        # It must NOT commit internally.

        report_reference = (
            await report_repository
            .submit_report(
                db=db,

                observer_id=observer_id,

                dive_session_id=(
                    report_data
                    .dive_session_id
                ),

                threat_category_code=(
                    threat_category["code"]
                ),

                description=(
                    report_data.description
                ),

                observed_at=(
                    report_data.observed_at
                ),

                location_source_code=(
                    location_source_code
                ),

                location_confidence_code=(
                    location_confidence[
                        "code"
                    ]
                ),

                evidence=evidence_items,

                estimated_depth_metres=(
                    report_data
                    .estimated_depth_metres
                ),

                latitude=latitude,
                longitude=longitude,

                relocation_notes=(
                    report_data.location
                    .relocation_notes
                ),
            )
        )

        # Obtain the response data while still inside the same DB
        # transaction. The session can see its own uncommitted writes.

        confirmation = (
            await report_repository
            .get_submission_confirmation(
                db=db,
                report_reference=(
                    report_reference
                ),
                observer_id=observer_id,
            )
        )

        if confirmation is None:
            raise DatabaseOperationError(
                "Submitted report could "
                "not be reloaded"
            )

        # Build the response BEFORE commit.
        # This prevents response-construction errors from occurring after
        # a successful commit.
        response = {
            "report_reference": (
                confirmation[
                    "report_reference"
                ]
            ),
            "status": (
                confirmation["status"]
            ),
            "submitted_at": (
                confirmation[
                    "submitted_at"
                ]
            ),
            "general_location": (
                confirmation[
                    "general_location"
                ]
            ),
        }

        # Commit only after the complete workflow succeeded.
        await db.commit()

        return response

    except (
        ReportValidationError,
        EvidenceValidationError,
        EvidenceStorageError,
    ):
        await db.rollback()

        await cleanup_private_evidence(
            stored_files
        )

        raise

    except DatabaseOperationError:
        await db.rollback()

        await cleanup_private_evidence(
            stored_files
        )

        raise

    except SQLAlchemyError as exc:
        await db.rollback()
        await cleanup_private_evidence(stored_files)

        # print("SQL ERROR:", repr(exc))

        raise DatabaseOperationError(
            "Unable to submit report"
        ) from exc

    except Exception as exc:
        await db.rollback()
        await cleanup_private_evidence(stored_files)

        # print("UNEXPECTED ERROR:", repr(exc))

        raise DatabaseOperationError(
            "Unexpected error while submitting report"
        ) from exc