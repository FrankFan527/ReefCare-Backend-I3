# ---------------------------------------------------------------------------
# US6.3 observer reply with photos (QA, Rifdhan 10 Oct).
#
# A Coordinator asks for, say, a wider photo of the net. Until now the
# Observer could answer only in text. This adds the photos to the same reply,
# on the same report, under the same Coordinator.
#
# Kept apart from information_service on purpose: evidence_service imports
# case_service, which imports information_service, so information_service
# cannot import evidence_service back. This module sits above both and is
# imported only by the route.
#
# Nothing new is needed in the database. Iteration 2 already reserved
# evidence.case_event_id = the info_provided event for observer responses,
# and the related-incident queries already read photos linked that way.
# ---------------------------------------------------------------------------

from fastapi import UploadFile
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    DatabaseOperationError,
    NotFoundError,
)
from app.repositories.case_action_repository import save_action_evidence
from app.repositories.information_repository import (
    get_latest_information_response_event_id,
)
from app.schemas.report import MAX_INFORMATION_RESPONSE_PHOTOS
from app.services import information_service as the_information_service
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
    An observer's answer plus photos, written as one unit (US6.3, QA 10 Oct).

    The coordinator asks for, say, a wider photo of the net. The answer and
    the photos either all arrive or none do: a half-saved reply would move
    the case back to under_review with the requested photo missing.

    Order matters:

      1. ownership and an open request, before reading any file
      2. the photo count, then every file validated, before anything is stored
      3. files stored privately
      4. the reply written through respond_to_information_request(), the same
         status move as a text reply, so the same coordinator keeps the case
      5. each photo linked to the reply's info_provided event, the link the
         Iteration 2 schema reserved for observer responses
      6. one commit; on any failure the transaction rolls back and every file
         stored in step 3 is deleted, so a retry starts clean

    Commits itself, unlike the text reply, because cleaning up stored files
    has to happen beside the rollback.
    """

    await the_information_service.load_report_with_open_request(
        db=db,
        report_reference=report_reference,
        observer_id=observer_id,
    )

    if len(photos) > MAX_INFORMATION_RESPONSE_PHOTOS:
        raise EvidenceValidationError(
            f"A reply can include at most {MAX_INFORMATION_RESPONSE_PHOTOS} photos"
        )

    # validate every file first, so one bad photo stores nothing at all
    the_validated_photos: list[tuple[UploadFile, bytes]] = []

    for the_photo in photos:
        the_content = await validate_photo(the_photo)
        the_validated_photos.append((the_photo, the_content))

    the_stored_files = []

    try:
        for the_photo, the_content in the_validated_photos:
            the_stored_files.append(
                await store_private_evidence(
                    photo=the_photo,
                    content=the_content,
                )
            )

        the_result = await the_information_service.respond_to_information_request(
            db=db,
            report_reference=report_reference,
            observer_id=observer_id,
            response_text=response_text,
        )

        the_case_event_id = await get_latest_information_response_event_id(
            db=db,
            report_reference=report_reference,
            observer_id=observer_id,
        )

        if the_case_event_id is None:
            raise DatabaseOperationError(
                "The reply history event could not be resolved"
            )

        the_evidence: list[dict] = []

        for the_stored_file in the_stored_files:
            the_saved = await save_action_evidence(
                db=db,
                report_reference=report_reference,
                case_event_id=the_case_event_id,
                uploaded_by_user_id=observer_id,
                file_reference=the_stored_file.file_reference,
                file_size_bytes=the_stored_file.file_size_bytes,
            )

            if the_saved is None:
                raise NotFoundError(f"Report {report_reference} not found")

            the_evidence.append(dict(the_saved))

        await db.commit()

    except Exception as the_error:
        await db.rollback()

        # never leave orphaned private files behind a reply that did not save
        for the_stored_file in the_stored_files:
            await delete_private_evidence(the_stored_file.file_reference)

        if isinstance(the_error, DBAPIError):
            # e.g. a second reply racing this one: the case already moved on
            raise ConflictError(
                "The response could not be recorded for this report"
            ) from the_error

        if isinstance(the_error, SQLAlchemyError):
            raise DatabaseOperationError(
                "The response could not be recorded for this report"
            ) from the_error

        raise

    return {
        **the_result,
        "case_event_id": the_case_event_id,
        "evidence": the_evidence,
    }
