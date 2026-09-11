from typing import Any

from fastapi import UploadFile
from sqlalchemy.exc import (
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    DatabaseOperationError,
)
from app.repositories import (
    reference_repository,
    report_repository,
)
from app.schemas.report import (
    ReportCreate,
)
from app.services.evidence_service import (
    EvidenceStorageError,
    EvidenceValidationError,
    StoredEvidence,
    cleanup_private_evidence,
    prepare_evidence_metadata,
    store_private_evidence,
    validate_photo,
)
from app.services.location_service import (
    LocationValidationError,
    normalise_observation_location,
)


class ReportValidationError(
    ValueError
):
    """
    Raised when report input passes Pydantic validation
    but violates an application/reference-data rule.
    """


def _normalise_location(
    report_data: ReportCreate,
) -> dict:
    """
    Convert ReportCreate.location into the canonical
    PostgreSQL location values.

    LocationValidationError is translated into the
    report-level validation error already handled by the
    reports route.
    """

    location = report_data.location

    map_pin = location.map_pin
    coordinates = location.coordinates

    try:
        return normalise_observation_location(
            named_dive_site_id=(
                location.named_dive_site_id
            ),

            submitted_source=(
                location.location_source
            ),

            submitted_confidence_code=(
                location.location_confidence
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

            relocation_notes=(
                location.relocation_notes
            ),
        )

    except LocationValidationError as exc:
        raise ReportValidationError(
            str(exc)
        ) from exc


async def _validate_reference_data(
    *,
    db: AsyncSession,
    report_data: ReportCreate,
    normalised_location: dict,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
]:
    """
    Resolve API values against PostgreSQL reference data.

    Location source is already normalised into one of the
    five canonical TC-407 values and is then checked
    against location_source.
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
                normalised_location[
                    "location_confidence_code"
                ]
            ),
        )
    )

    if location_confidence is None:
        raise ReportValidationError(
            "Unknown location confidence"
        )

    location_source = (
        await reference_repository
        .get_location_source(
            db=db,
            code=(
                normalised_location[
                    "location_source_code"
                ]
            ),
        )
    )

    if location_source is None:
        raise ReportValidationError(
            "Configured location source "
            "is not available"
        )

    return (
        dict(threat_category),
        dict(location_confidence),
    )


async def _store_evidence_files(
    photos: list[UploadFile],
) -> tuple[
    list[StoredEvidence],
    list[dict[str, Any]],
]:
    """
    Validate and privately store every uploaded photo.
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
    Submit a complete observation report.

    TC-407:
    all five location provenance codes are now preserved
    distinctly from request validation through PostgreSQL
    persistence.

    PostgreSQL remains authoritative for final submission,
    report creation, location creation, evidence rows and
    workflow events.
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
        # Normalise before any evidence is stored.
        normalised_location = (
            _normalise_location(
                report_data
            )
        )

        (
            threat_category,
            location_confidence,
        ) = await _validate_reference_data(
            db=db,
            report_data=report_data,
            normalised_location=(
                normalised_location
            ),
        )

        dive_session = (
            await report_repository
            .get_owned_dive_session(
                db,
                dive_session_id=(
                    report_data
                    .dive_session_id
                ),
                observer_id=observer_id,
            )
        )

        if dive_session is None:
            raise ReportValidationError(
                "Dive session does not belong "
                "to the current observer"
            )

        if (
            report_data
            .location
            .named_dive_site_id
            != dive_session[
                "dive_site_id"
            ]
        ):
            raise ReportValidationError(
                "Dive site does not match "
                "the selected dive session"
            )

        (
            stored_files,
            evidence_items,
        ) = await _store_evidence_files(
            photos
        )

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
                    normalised_location[
                        "location_source_code"
                    ]
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

                latitude=(
                    normalised_location[
                        "latitude"
                    ]
                ),

                longitude=(
                    normalised_location[
                        "longitude"
                    ]
                ),

                relocation_notes=(
                    normalised_location[
                        "relocation_notes"
                    ]
                ),
            )
        )

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

        response = {
            "report_reference":
                confirmation[
                    "report_reference"
                ],

            "status":
                confirmation["status"],

            "submitted_at":
                confirmation[
                    "submitted_at"
                ],

            "general_location":
                confirmation[
                    "general_location"
                ],
        }

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

        await cleanup_private_evidence(
            stored_files
        )

        raise DatabaseOperationError(
            "Unable to submit report"
        ) from exc

    except Exception as exc:
        await db.rollback()

        await cleanup_private_evidence(
            stored_files
        )

        raise DatabaseOperationError(
            "Unexpected error while "
            "submitting report"
        ) from exc