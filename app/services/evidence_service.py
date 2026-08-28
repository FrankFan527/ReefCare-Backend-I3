from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

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


def _get_storage_root() -> Path:
    """
    Return the root directory used for development evidence storage.

    For the current repository this falls back to ./private_evidence
    when evidence_storage_dir has not yet been added to Settings.

    In production this function can later be replaced by an
    R2/S3/Supabase storage adapter without changing the report
    submission contract.
    """

    configured_path = getattr(
        settings,
        "evidence_storage_dir",
        "./private_evidence",
    )

    return Path(configured_path)


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
        raise EvidenceValidationError(
            "Photo exceeds the maximum allowed size "
            "of 10 MB"
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
    Store a validated evidence file in private development storage.

    The returned file_reference is a storage key such as:

        evidence/a84d...9f.jpg

    It is deliberately NOT a public URL.

    Do not mount the private_evidence directory using FastAPI
    StaticFiles.

    Production object storage can later replace the implementation
    inside this function without changing callers.
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

    storage_root = _get_storage_root()

    destination = (
        storage_root / object_key
    )

    try:
        await run_in_threadpool(
            destination.parent.mkdir,
            parents=True,
            exist_ok=True,
        )

        await run_in_threadpool(
            destination.write_bytes,
            content,
        )

    except OSError as exc:
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
    Delete one private evidence object.

    Used when the PostgreSQL submission fails after files
    have already been stored.

    Cleanup is best-effort so a cleanup problem does not hide
    the original submission exception.
    """

    storage_root = _get_storage_root()

    target = (
        storage_root / file_reference
    )

    try:
        await run_in_threadpool(
            target.unlink,
            missing_ok=True,
        )
    except OSError:
        # Best-effort cleanup.
        # Once logging.py exists this should be logged.
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