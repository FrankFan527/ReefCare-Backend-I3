"""Local ONNX ResNet18 features and exact cosine KNN over cached arrays."""

import asyncio
import hashlib
import io
import logging
import threading
import warnings

from dataclasses import replace
from functools import lru_cache
from math import isfinite, sqrt
from pathlib import Path

import numpy as np

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import (
    image_embedding_repository as repository,
)
from app.schemas.related_incident import (
    ImageAnalysisState,
    ImageEmbedding,
    ReportComparisonFacts,
)
from app.services.evidence_service import (
    MAX_PHOTO_BYTES,
    _get_supabase_client,
)


logger = logging.getLogger(__name__)

IMAGE_MODEL = (
    "torchvision-resnet18-imagenet1k-v1"
)

IMAGE_VERSION = (
    "avgpool512-rgb-exif-resize256-"
    "centercrop224-l2-v1"
)

EMBEDDING_DIMENSIONS = 512

RESIZE_SHORT_SIDE = 256
CROP_SIZE = 224

IMAGENET_MEAN = np.asarray(
    (0.485, 0.456, 0.406),
    dtype=np.float32,
)

IMAGENET_STD = np.asarray(
    (0.229, 0.224, 0.225),
    dtype=np.float32,
)

_inference_lock = threading.Lock()
_download_slot = threading.BoundedSemaphore(1)


def normalise_vector(
    values,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> tuple[float, ...] | None:

    if values is None or isinstance(
        values,
        (str, bytes),
    ):
        return None

    try:
        vector = tuple(
            float(value)
            for value in values
        )

        if (
            len(vector) != dimensions
            or not all(
                isfinite(value)
                for value in vector
            )
        ):
            return None

        norm = sqrt(
            sum(
                value * value
                for value in vector
            )
        )

        if (
            not isfinite(norm)
            or norm <= 1e-12
        ):
            return None

        return tuple(
            value / norm
            for value in vector
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def embedding_from_row(
    row: dict,
) -> ImageEmbedding | None:

    if (
        row.get(
            "image_embedding_model"
        ) != IMAGE_MODEL
        or row.get(
            "image_embedding_version"
        ) != IMAGE_VERSION
        or row.get(
            "image_embedding_generated_at"
        ) is None
    ):
        return None

    vector = normalise_vector(
        row.get("image_embedding")
    )

    if vector is None:
        return None

    return ImageEmbedding(
        row["evidence_id"],
        vector,
        IMAGE_MODEL,
        IMAGE_VERSION,
    )


def nearest_image_reports(
    source: ReportComparisonFacts,
    pool: list[ReportComparisonFacts],
    top_k: int = 10,
) -> dict[int, float]:

    scores: dict[int, float] = {}

    history = []

    for report in pool:

        if (
            report.report_id
            == source.report_id
        ):
            continue

        for image in (
            report.image_embeddings
        ):

            if (
                image.model,
                image.version,
            ) != (
                IMAGE_MODEL,
                IMAGE_VERSION,
            ):
                continue

            vector = normalise_vector(
                image.vector
            )

            if vector is not None:
                history.append(
                    (
                        report.report_id,
                        image.evidence_id,
                        vector,
                    )
                )

    for query in source.image_embeddings:

        query_vector = normalise_vector(
            query.vector
        )

        if (
            (
                query.model,
                query.version,
            )
            != (
                IMAGE_MODEL,
                IMAGE_VERSION,
            )
            or query_vector is None
        ):
            continue

        neighbours = []

        for (
            report_id,
            evidence_id,
            vector,
        ) in history:

            cosine = max(
                -1.0,
                min(
                    1.0,
                    sum(
                        a * b
                        for a, b in zip(
                            query_vector,
                            vector,
                        )
                    ),
                ),
            )

            neighbours.append(
                (
                    1 - cosine,
                    report_id,
                    evidence_id,
                )
            )

        for (
            distance,
            report_id,
            _,
        ) in sorted(
            neighbours
        )[:max(1, top_k)]:

            scores[report_id] = max(
                scores.get(
                    report_id,
                    0.0,
                ),
                max(
                    0.0,
                    1 - distance,
                ),
            )

    return scores


def _sha256_file(
    path: Path,
) -> str:

    digest = hashlib.sha256()

    with path.open("rb") as handle:

        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


@lru_cache(maxsize=1)
def _load_model(
    model_path: str,
):
    """
    Load one ONNX Runtime session per warm
    application instance.
    """

    import onnxruntime as ort

    path = Path(
        model_path
    ).expanduser()

    if not path.is_file():
        raise FileNotFoundError(
            "ONNX image embedding model "
            "is not installed"
        )

    checksum_path = path.with_suffix(
        path.suffix + ".sha256"
    )

    if not checksum_path.is_file():
        raise FileNotFoundError(
            "ONNX model checksum "
            "is not installed"
        )

    expected = (
        checksum_path
        .read_text(
            encoding="utf-8"
        )
        .strip()
        .split()[0]
        .lower()
    )

    actual = _sha256_file(path)

    if (
        len(expected) != 64
        or actual != expected
    ):
        raise ValueError(
            "Unexpected ONNX image "
            "model checksum"
        )

    options = ort.SessionOptions()

    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1

    options.execution_mode = (
        ort.ExecutionMode
        .ORT_SEQUENTIAL
    )

    session = ort.InferenceSession(
        str(path),
        sess_options=options,
        providers=[
            "CPUExecutionProvider"
        ],
    )

    input_name = (
        session
        .get_inputs()[0]
        .name
    )

    output_name = (
        session
        .get_outputs()[0]
        .name
    )

    return (
        session,
        input_name,
        output_name,
    )


def _resize_shorter_side(
    image,
    size: int = RESIZE_SHORT_SIDE,
):
    from PIL import Image

    width, height = image.size

    if (
        width <= 0
        or height <= 0
    ):
        raise ValueError(
            "Invalid image dimensions"
        )

    if width <= height:

        new_width = size

        new_height = max(
            size,
            int(
                round(
                    height
                    * size
                    / width
                )
            ),
        )

    else:

        new_height = size

        new_width = max(
            size,
            int(
                round(
                    width
                    * size
                    / height
                )
            ),
        )

    return image.resize(
        (
            new_width,
            new_height,
        ),
        resample=(
            Image.Resampling.BILINEAR
        ),
    )


def _preprocess_image(
    image,
) -> np.ndarray:

    image = _resize_shorter_side(
        image
    )

    width, height = image.size

    left = int(
        round(
            (
                width
                - CROP_SIZE
            )
            / 2.0
        )
    )

    top = int(
        round(
            (
                height
                - CROP_SIZE
            )
            / 2.0
        )
    )

    image = image.crop(
        (
            left,
            top,
            left + CROP_SIZE,
            top + CROP_SIZE,
        )
    )

    array = np.asarray(
        image,
        dtype=np.float32,
    )

    array /= np.float32(
        255.0
    )

    array = (
        array
        - IMAGENET_MEAN
    ) / IMAGENET_STD

    array = np.transpose(
        array,
        (
            2,
            0,
            1,
        ),
    )[None, ...]

    return np.ascontiguousarray(
        array,
        dtype=np.float32,
    )


def embed_image(
    content: bytes,
) -> tuple[float, ...]:

    if (
        not content
        or len(content)
        > MAX_PHOTO_BYTES
    ):
        raise ValueError(
            "Image is empty or exceeds "
            "the evidence size limit"
        )

    from PIL import (
        Image,
        ImageOps,
    )

    with (
        _inference_lock,
        warnings.catch_warnings(),
    ):

        warnings.simplefilter(
            "error",
            Image.DecompressionBombWarning,
        )

        with Image.open(
            io.BytesIO(content)
        ) as original:

            if original.format not in {
                "JPEG",
                "PNG",
                "WEBP",
            }:
                raise ValueError(
                    "Unsupported evidence "
                    "image format"
                )

            if (
                original.width
                * original.height
                > settings
                .related_incident_image_max_pixels
            ):
                raise ValueError(
                    "Image exceeds decoded "
                    "pixel limit"
                )

            original.load()

            image = (
                ImageOps
                .exif_transpose(
                    original
                )
                .convert("RGB")
            )

            tensor = (
                _preprocess_image(
                    image
                )
            )

        (
            session,
            input_name,
            output_name,
        ) = _load_model(
            settings
            .related_incident_image_model_path
        )

        output = session.run(
            [output_name],
            {
                input_name: tensor
            },
        )[0]

    if output.shape != (
        1,
        EMBEDDING_DIMENSIONS,
    ):
        raise ValueError(
            "Image model produced "
            "unexpected output shape"
        )

    vector = normalise_vector(
        output[0].tolist()
    )

    if vector is None:
        raise ValueError(
            "Image model produced "
            "invalid features"
        )

    return vector


def _download_and_embed(
    file_reference: str,
) -> tuple[float, ...]:

    if not _download_slot.acquire(
        blocking=False
    ):
        raise RuntimeError(
            "Image embedding service "
            "is busy"
        )

    try:

        content = (
            _get_supabase_client()
            .storage
            .from_(
                settings
                .supabase_storage_bucket
            )
            .download(
                file_reference
            )
        )

        return embed_image(
            content
        )

    finally:
        _download_slot.release()


async def generate_missing_embeddings(
    db: AsyncSession,
    rows: list[dict],
) -> list[dict]:

    updated = [
        dict(row)
        for row in rows
    ]

    for row in updated:

        if (
            embedding_from_row(row)
            is not None
        ):
            continue

        try:

            vector = (
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _download_and_embed,
                        row[
                            "file_reference"
                        ],
                    ),
                    timeout=(
                        settings
                        .related_incident_image_timeout_seconds
                    ),
                )
            )

        except Exception as error:

            logger.warning(
                "Image embedding unavailable "
                "for evidence %s (%s)",
                row["evidence_id"],
                type(error).__name__,
            )

            continue

        saved = (
            await repository
            .save_embedding(
                db,
                row["evidence_id"],
                row[
                    "file_reference"
                ],
                vector,
                IMAGE_MODEL,
                IMAGE_VERSION,
            )
        )

        if saved:

            row.update(
                image_embedding=vector,
                image_embedding_model=(
                    IMAGE_MODEL
                ),
                image_embedding_version=(
                    IMAGE_VERSION
                ),
            )

    return updated


def attach_embeddings(source: ReportComparisonFacts, pool: list[ReportComparisonFacts], rows: list[dict]):
    by_report: dict[int, list[ImageEmbedding]] = {}
    for row in rows:
        embedding = embedding_from_row(row)
        if embedding:
            by_report.setdefault(row["report_id"], []).append(embedding)
    source = replace(source, image_embeddings=tuple(by_report.get(source.report_id, ())))
    pool = [replace(report, image_embeddings=tuple(by_report.get(report.report_id, ()))) for report in pool]
    source_rows = [row for row in rows if row["report_id"] == source.report_id]
    history_rows = [row for row in rows if row["report_id"] != source.report_id]
    if not source_rows:
        state = ImageAnalysisState.NO_SOURCE_IMAGES
    elif not source.image_embeddings:
        state = ImageAnalysisState.UNAVAILABLE
    elif not any(report.image_embeddings for report in pool):
        state = ImageAnalysisState.INSUFFICIENT_HISTORY
    elif len(source.image_embeddings) < len(source_rows) or sum(len(report.image_embeddings) for report in pool) < len(history_rows):
        state = ImageAnalysisState.PARTIAL
    else:
        state = ImageAnalysisState.READY
    return source, pool, state
