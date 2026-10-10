# ---------------------------------------------------------------------------
# US6.3 Observer reply with photos (QA, Rifdhan 10 Oct).
#
# A Coordinator may ask the Observer for additional information, for example:
#
#     "Please upload a wider photo of the net."
#
# Previously the Observer could answer only with text.
#
# This service extends that existing information-response flow so the Observer
# may return text plus private supporting photos while preserving:
#
# - the same report
# - the same claiming Coordinator
# - the existing needs_more_info -> under_review transition
# - the append-only case_event audit history
# - private evidence storage
#
# The module intentionally sits above information_service and evidence_service.
#
# evidence_service imports case_service, which ultimately depends on the
# information workflow. Keeping evidence orchestration here avoids creating a
# circular service dependency.
#
# Database design:
#
#   case_event
#       info_requested
#       info_provided
#
#   evidence.case_event_id
#       -> the info_provided event created for this response
#
# No new database table or migration is required.
# ---------------------------------------------------------------------------

from fastapi import UploadFile

from sqlalchemy.exc import (
    DBAPIError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.core.exceptions import (
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
)

from app.repositories.information_repository import (
    get_latest_information_response_event_id,
    save_information_response_evidence,
)

from app.schemas.report import (
    MAX_INFORMATION_RESPONSE_PHOTOS,
)

from app.services import (
    information_service
    as the_information_service,
)

from app.services.evidence_service import (
    EvidenceValidationError,
    delete_private_evidence,
    store_private_evidence,
    validate_photo,
)


async def respond_to_information_request_with_photos(
    db: AsyncSession,
    report_reference: str,
    observer_id: int,
    response_text: str,
    photos: list[UploadFile],
) -> dict:
    """
    Record one Observer information response together with
    zero or more private photos.

    The reply and photos are treated as one logical unit.

    Sequence:

    1. Verify that the report belongs to this Observer and
       currently has an open information request.

    2. Validate the photo count and every uploaded file
       before storing anything.

    3. Store validated files privately in Supabase.

    4. Use the existing information response workflow to
       create the info_provided event and move the case from
       needs_more_info back to under_review.

    5. Resolve the newly-created info_provided case_event.

    6. Persist evidence metadata linked to that case_event.

    7. Commit once.

    If any database/storage step fails:

    - the database transaction is rolled back
    - every private object already stored by this request is
      removed best-effort
    - the original report and Coordinator assignment remain
      unchanged

    This service commits itself because storage cleanup and
    database rollback must be coordinated in one place.
    """

    # ------------------------------------------------------------------
    # Ownership + workflow check.
    #
    # This happens before any file bytes are read or stored.
    # ------------------------------------------------------------------

    await (
        the_information_service
        .load_report_with_open_request(
            db=db,

            report_reference=(
                report_reference
            ),

            observer_id=(
                observer_id
            ),
        )
    )

    # ------------------------------------------------------------------
    # File-count boundary.
    # ------------------------------------------------------------------

    if (
        len(photos)
        >
        MAX_INFORMATION_RESPONSE_PHOTOS
    ):
        raise EvidenceValidationError(
            "A reply can include at most "
            f"{MAX_INFORMATION_RESPONSE_PHOTOS} "
            "photos"
        )

    # ------------------------------------------------------------------
    # Validate every photo before storing any photo.
    #
    # One invalid photo therefore causes zero objects to be
    # written to private storage.
    # ------------------------------------------------------------------

    the_validated_photos: list[
        tuple[
            UploadFile,
            bytes,
        ]
    ] = []

    for the_photo in photos:
        the_content = (
            await validate_photo(
                the_photo
            )
        )

        the_validated_photos.append(
            (
                the_photo,
                the_content,
            )
        )

    # StoredEvidence objects written during this request.
    #
    # If anything after storage fails, these object keys are
    # removed best-effort so retries do not leave orphans.
    the_stored_files = []

    try:
        # --------------------------------------------------------------
        # Store every validated photo privately.
        # --------------------------------------------------------------

        for (
            the_photo,
            the_content,
        ) in the_validated_photos:
            the_stored_file = (
                await store_private_evidence(
                    photo=the_photo,
                    content=the_content,
                )
            )

            the_stored_files.append(
                the_stored_file
            )

        # --------------------------------------------------------------
        # Record the normal Observer information response.
        #
        # This uses the existing canonical flow:
        #
        # needs_more_info
        #       ->
        # under_review
        #
        # and creates an info_provided case_event.
        #
        # It deliberately does not commit.
        # --------------------------------------------------------------

        the_result = (
            await (
                the_information_service
                .respond_to_information_request(
                    db=db,

                    report_reference=(
                        report_reference
                    ),

                    observer_id=(
                        observer_id
                    ),

                    response_text=(
                        response_text
                    ),
                )
            )
        )

        # --------------------------------------------------------------
        # Resolve the exact Observer info_provided event that
        # was just created.
        #
        # Evidence is attached to this event, not merely to
        # the general report.
        # --------------------------------------------------------------

        the_case_event_id = (
            await (
                get_latest_information_response_event_id(
                    db=db,

                    report_reference=(
                        report_reference
                    ),

                    observer_id=(
                        observer_id
                    ),
                )
            )
        )

        if the_case_event_id is None:
            raise DatabaseOperationError(
                "The reply history event "
                "could not be resolved"
            )

        # --------------------------------------------------------------
        # Persist safe evidence metadata.
        #
        # The repository independently verifies that:
        #
        # - report belongs to Observer
        # - event belongs to report
        # - event is info_provided
        # - event actor is Observer
        # --------------------------------------------------------------

        the_evidence: list[
            dict
        ] = []

        for (
            the_stored_file
        ) in the_stored_files:
            the_saved = (
                await (
                    save_information_response_evidence(
                        db=db,

                        report_reference=(
                            report_reference
                        ),

                        case_event_id=(
                            the_case_event_id
                        ),

                        observer_id=(
                            observer_id
                        ),

                        file_reference=(
                            the_stored_file
                            .file_reference
                        ),

                        file_size_bytes=(
                            the_stored_file
                            .file_size_bytes
                        ),
                    )
                )
            )

            if the_saved is None:
                raise NotFoundError(
                    f"Report "
                    f"{report_reference} "
                    f"not found"
                )

            the_evidence.append(
                dict(
                    the_saved
                )
            )

        # --------------------------------------------------------------
        # One transaction boundary for:
        #
        # - status transition
        # - info_provided event
        # - evidence metadata
        # --------------------------------------------------------------

        await db.commit()

    except Exception as the_error:
        # --------------------------------------------------------------
        # Database rollback.
        # --------------------------------------------------------------

        await db.rollback()

        # --------------------------------------------------------------
        # Private-storage compensation.
        #
        # Supabase is outside the PostgreSQL transaction, so
        # any objects uploaded before the DB failure must be
        # removed manually.
        # --------------------------------------------------------------

        for (
            the_stored_file
        ) in the_stored_files:
            await delete_private_evidence(
                the_stored_file
                .file_reference
            )

        # --------------------------------------------------------------
        # Concurrent/invalid workflow transition.
        #
        # Example:
        #
        # Two reply requests race and the first one already
        # moved the report out of needs_more_info.
        # --------------------------------------------------------------

        if isinstance(
            the_error,
            DBAPIError,
        ):
            raise ConflictError(
                "The response could not be "
                "recorded for this report"
            ) from the_error

        # --------------------------------------------------------------
        # Other SQLAlchemy/database failure.
        # --------------------------------------------------------------

        if isinstance(
            the_error,
            SQLAlchemyError,
        ):
            raise DatabaseOperationError(
                "The response could not be "
                "recorded for this report"
            ) from the_error

        # Preserve domain/storage/validation exceptions for
        # the route layer to translate normally.
        raise

    return {
        **the_result,

        "case_event_id":
            the_case_event_id,

        "evidence":
            the_evidence,
    }