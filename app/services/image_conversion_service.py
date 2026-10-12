from dataclasses import dataclass
from io import BytesIO

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.services.evidence_service import (
    ALLOWED_PHOTO_TYPES,
    MAX_PHOTO_BYTES,
    EvidenceTooLargeError,
    EvidenceValidationError,
    validate_photo,
)


# Register HEIC/HEIF support if installed.
try:
    from pillow_heif import register_heif_opener
except ImportError:
    pass
else:
    register_heif_opener()


# Image formats that require conversion.
CONVERTIBLE_FORMATS = frozenset({
    "BMP",
    "GIF",
    "TIFF",
    "ICO",
    "AVIF",
    "HEIF",
    "HEIC",
})

# Maximum decoded image size.
MAX_DECODED_PIXELS = 60_000_000

# Maximum output image width or height.
MAX_OUTPUT_DIMENSION = 4096

# Compression quality.
JPEG_QUALITY = 85
WEBP_QUALITY = 85


@dataclass(frozen=True, slots=True)
class PreparedReportPhoto:
    content: bytes
    content_type: str


def _encode_image(
    image: Image.Image,
    image_format: str,
) -> bytes:
    """
    Encode an image into JPEG, PNG, or WebP.
    """

    buffer = BytesIO()

    if image_format == "JPEG":
        image.save(
            buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            subsampling=0,
        )

    elif image_format == "WEBP":
        image.save(
            buffer,
            format="WEBP",
            quality=WEBP_QUALITY,
            method=5,
        )

    elif image_format == "PNG":
        image.save(
            buffer,
            format="PNG",
            optimize=True,
        )

    return buffer.getvalue()


def _convert_image(
    content: bytes,
) -> PreparedReportPhoto:
    """
    Convert unsupported image formats into
    JPEG, PNG, or WebP.

    Select the smallest suitable output.
    """

    try:
        with Image.open(BytesIO(content)) as opened:

            # Check supported conversion formats.
            if opened.format not in CONVERTIBLE_FORMATS:
                raise EvidenceValidationError(
                    "Unsupported photo format. "
                    "Supported uploads are JPEG, PNG, WebP, "
                    "BMP, GIF (static), TIFF, ICO, "
                    "AVIF and HEIC/HEIF."
                )

            # Reject animated or multi-page images.
            if getattr(opened, "n_frames", 1) > 1:
                raise EvidenceValidationError(
                    "Animated or multi-page images "
                    "are not supported"
                )

            # Validate decoded image dimensions.
            width, height = opened.size

            if (
                width <= 0
                or height <= 0
                or width * height > MAX_DECODED_PIXELS
            ):
                raise EvidenceTooLargeError(
                    "Photo exceeds the maximum "
                    "decoded image size"
                )

            # Decode the image.
            opened.load()

            # Correct image orientation.
            oriented = ImageOps.exif_transpose(opened)

            # Automatically resize large images.
            if (
                oriented.width > MAX_OUTPUT_DIMENSION
                or oriented.height > MAX_OUTPUT_DIMENSION
            ):
                oriented.thumbnail(
                    (
                        MAX_OUTPUT_DIMENSION,
                        MAX_OUTPUT_DIMENSION,
                    ),
                    Image.Resampling.LANCZOS,
                )

            # Check transparency.
            has_alpha = (
                "A" in oriented.getbands()
                or "transparency" in oriented.info
            )

            if has_alpha:
                normalized = oriented.convert("RGBA")

                # JPEG does not support transparency.
                formats = [
                    ("PNG", "image/png"),
                    ("WEBP", "image/webp"),
                ]

            else:
                normalized = oriented.convert("RGB")

                formats = [
                    ("JPEG", "image/jpeg"),
                    ("PNG", "image/png"),
                    ("WEBP", "image/webp"),
                ]

            candidates = []

            # Convert into all eligible formats.
            for image_format, content_type in formats:

                try:
                    converted_content = _encode_image(
                        normalized,
                        image_format,
                    )

                except (OSError, ValueError):
                    continue

                # Only accept images within size limit.
                if len(converted_content) <= MAX_PHOTO_BYTES:

                    candidates.append(
                        PreparedReportPhoto(
                            content=converted_content,
                            content_type=content_type,
                        )
                    )

            # Check whether conversion succeeded.
            if not candidates:
                raise EvidenceTooLargeError(
                    "Converted photo exceeds the "
                    "maximum allowed size or no "
                    "suitable encoder is available"
                )

            # Select the smallest converted image.
            smallest_image = min(
                candidates,
                key=lambda image: len(image.content),
            )

            return smallest_image

    except EvidenceValidationError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:

        raise EvidenceValidationError(
            "Uploaded file cannot be decoded "
            "as a supported image"
        ) from exc


async def prepare_report_photo(
    photo: UploadFile,
) -> PreparedReportPhoto:
    """
    Prepare an uploaded report photo.

    JPEG, PNG, WebP:
        Validate and keep original.

    Other supported formats:
        Convert and select smallest output.
    """

    content_type = (
        (photo.content_type or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    # Existing supported formats.
    # No conversion is required.
    if content_type in ALLOWED_PHOTO_TYPES:

        content = await validate_photo(photo)

        return PreparedReportPhoto(
            content=content,
            content_type=content_type,
        )

    # Read uploaded image.
    content = await photo.read(
        MAX_PHOTO_BYTES + 1
    )

    # Reject empty files.
    if not content:
        raise EvidenceValidationError(
            "Uploaded photo is empty"
        )

    # Check original file size.
    if len(content) > MAX_PHOTO_BYTES:
        raise EvidenceTooLargeError(
            "Photo exceeds the maximum allowed "
            "size of 10 MB"
        )

    # Perform conversion outside the event loop.
    return await run_in_threadpool(
        _convert_image,
        content,
    )