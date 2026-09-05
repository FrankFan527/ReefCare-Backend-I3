from dataclasses import dataclass
from functools import lru_cache
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool
from supabase import Client, create_client

from app.core.config import settings

from app.core.exceptions import (
    NotFoundError,
)
from app.repositories.evidence_repository import (
    get_case_evidence,
)
from app.services.case_service import (
    get_owned_case,
)

import mimetypes

ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

MAX_PHOTO_BYTES = 10 * 1024 * 1024 # 10 MB

class EvidenceValidationError(ValueError):
    """
    Raised when an uploaded evidence file is invalid.
    """


class EvidenceTooLargeError(EvidenceValidationError):
    """
    Raised when an uploaded evidence file exceeds the maximum allowed size.
    """
    pass


class EvidenceStorageError(Exception):
    """
    Raised when evidence cannot be written to private storage.
    """


@dataclass(slots=True)
class StoredEvidence:
    """
    Metadata about a successfully stored private evidence object.

    Only file_reference is persisted by the current
    reefcare_submit_report() function.

    file_size_bytes and content_type remain useful to the
    application even though the current SQL function does
    not persist file_size_bytes.
    """

    file_reference: str
    file_size_bytes: int
    content_type: str


@lru_cache
def _get_supabase_client() -> Client:
    """
    Return the server-side Supabase client used for
    private evidence storage.

    The configured secret key must never be exposed
    to frontend code.
    """

    return create_client(
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
    )


def _validate_file_signature(
    content_type: str,
    content: bytes,
) -> None:
    """
    Perform a small integrity check against common image magic bytes.

    This is not intended to deeply inspect or transform the image.
    """

    if content_type == "image/jpeg":
        if not content.startswith(b"\xff\xd8\xff"):
            raise EvidenceValidationError(
                "Uploaded file is not a valid JPEG image"
            )

    elif content_type == "image/png":
        if not content.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            raise EvidenceValidationError(
                "Uploaded file is not a valid PNG image"
            )

    elif content_type == "image/webp":
        if (
            len(content) < 12
            or not content.startswith(b"RIFF")
            or content[8:12] != b"WEBP"
        ):
            raise EvidenceValidationError(
                "Uploaded file is not a valid WebP image"
            )


@dataclass(slots=True)
class EvidenceFile:
    """
    Private evidence bytes after ownership and
    report/evidence checks have succeeded.
    """

    content: bytes
    content_type: str


def _content_type_for_reference(
    file_reference: str,
) -> str:
    """
    Infer the response MIME type from the
    private object key.
    """

    guessed_type, _ = (
        mimetypes.guess_type(
            file_reference
        )
    )

    if guessed_type in ALLOWED_PHOTO_TYPES:
        return guessed_type

    return "application/octet-stream"


async def get_case_evidence_file(
    *,
    db,
    report_reference: str,
    evidence_id: int,
    coordinator_id: int,
) -> EvidenceFile:
    """
    Return private evidence only to the
    coordinator who currently owns the case.

    Security sequence:

    1. Verify case ownership.
    2. Verify evidence belongs to the report.
    3. Download the private object server-side.
    4. Return bytes without exposing the object key.
    """

    # First security boundary:
    # coordinator must currently own this report.
    await get_owned_case(
        db=db,
        report_reference=(
            report_reference
        ),
        coordinator_id=(
            coordinator_id
        ),
    )

    # Second security boundary:
    # evidence must actually belong to this report.
    evidence = await get_case_evidence(
        db=db,
        report_reference=(
            report_reference
        ),
        evidence_id=evidence_id,
    )

    if evidence is None:
        # Do not reveal whether the evidence
        # belongs to a different case.
        raise NotFoundError(
            "Evidence not found"
        )

    file_reference = (
        evidence["file_reference"]
    )

    def download_object():
        client = _get_supabase_client()

        return (
            client.storage
            .from_(
                settings
                .supabase_storage_bucket
            )
            .download(
                file_reference
            )
        )

    try:
        content = await run_in_threadpool(
            download_object
        )

    except Exception as exc:
        raise EvidenceStorageError(
            "Unable to load private evidence"
        ) from exc

    return EvidenceFile(
        content=content,
        content_type=(
            _content_type_for_reference(
                file_reference
            )
        ),
    )


async def validate_photo(
    photo: UploadFile,
) -> bytes:
    """
    Validate one uploaded photo.

    Checks:
    - supported media type
    - file is not empty
    - maximum application file size
    - basic file signature

    Returns the validated file bytes.

    Raises:
        EvidenceValidationError
    """

    content_type = (
        photo.content_type or ""
    ).lower()

    if content_type not in ALLOWED_PHOTO_TYPES:
        raise EvidenceValidationError(
            "Unsupported photo type. "
            "Allowed types are JPEG, PNG and WebP."
        )

    # Read only one byte beyond the maximum so an extremely
    # large upload is not unnecessarily loaded into memory.
    content = await photo.read(
        MAX_PHOTO_BYTES + 1
    )

    if not content:
        raise EvidenceValidationError(
            "Uploaded photo is empty"
        )

    if len(content) > MAX_PHOTO_BYTES:
        raise EvidenceTooLargeError(
            f"Photo exceeds the maximum allowed size "
            f"of {MAX_PHOTO_BYTES // (1024 * 1024)} MB"
        )

    _validate_file_signature(
        content_type=content_type,
        content=content,
    )

    return content


async def store_private_evidence(
    *,
    photo: UploadFile,
    content: bytes,
) -> StoredEvidence:
    """
    Store validated evidence in the private
    Supabase Storage bucket.

    The returned file_reference is an opaque
    storage object key, not a public URL.
    """

    content_type = (
        photo.content_type or ""
    ).lower()

    extension = ALLOWED_PHOTO_TYPES.get(
        content_type
    )

    if extension is None:
        raise EvidenceValidationError(
            "Unsupported photo type"
        )

    object_key = (
        f"evidence/{uuid4().hex}{extension}"
    )

    def upload_object():
        client = _get_supabase_client()

        return (
            client.storage
            .from_(
                settings.supabase_storage_bucket
            )
            .upload(
                path=object_key,
                file=content,
                file_options={
                    "content-type": content_type,
                    "upsert": "false",
                },
            )
        )

    try:
        await run_in_threadpool(
            upload_object
        )

    except Exception as exc:
        raise EvidenceStorageError(
            "Unable to store private evidence"
        ) from exc

    return StoredEvidence(
        file_reference=object_key,
        file_size_bytes=len(content),
        content_type=content_type,
    )


def prepare_evidence_metadata(
    *,
    stored_file: StoredEvidence,
    captured_at=None,
) -> dict:
    """
    Convert stored-file information to the exact JSON shape consumed by
    PostgreSQL reefcare_submit_report().

    Current SQL reads:
        media_type
        file_reference
        captured_at

    The current SQL function does NOT persist:
        file_size_bytes
        checksum
        display_order

    Therefore those values are deliberately not placed into the JSONB
    submission payload.

    captured_at is optional in Iteration 1. No EXIF extraction is
    performed here.
    """

    if captured_at is None:
        captured_at_value = None
    elif hasattr(captured_at, "isoformat"):
        captured_at_value = (
            captured_at.isoformat()
        )
    else:
        captured_at_value = str(
            captured_at
        )

    return {
        "media_type": "photo",
        "file_reference":
            stored_file.file_reference,
        "captured_at":
            captured_at_value,
    }


async def delete_private_evidence(
    file_reference: str,
) -> None:
    """
    Best-effort deletion of a private Supabase
    Storage object.

    Used to compensate when database report
    submission fails after evidence was uploaded.
    """

    def remove_object():
        client = _get_supabase_client()

        return (
            client.storage
            .from_(
                settings.supabase_storage_bucket
            )
            .remove(
                [file_reference]
            )
        )

    try:
        await run_in_threadpool(
            remove_object
        )

    except Exception:
        # Best-effort cleanup.
        # Log this when application logging is introduced.
        pass


async def cleanup_private_evidence(
    stored_files: list[StoredEvidence],
) -> None:
    """
    Best-effort cleanup for all evidence files stored during
    a submission attempt.
    """

    for stored_file in stored_files:
        await delete_private_evidence(
            stored_file.file_reference
        )