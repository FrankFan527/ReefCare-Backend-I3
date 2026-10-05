"""Local, optional ResNet18 features and exact cosine KNN over cached arrays.

Images stay inside the backend. No public URLs, third-party AI uploads, or
automatic weight downloads. Imports of heavy worker dependencies are lazy.
"""

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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import image_embedding_repository as repository
from app.schemas.related_incident import ImageAnalysisState, ImageEmbedding, ReportComparisonFacts
from app.services.evidence_service import MAX_PHOTO_BYTES, _get_supabase_client

logger = logging.getLogger(__name__)
IMAGE_MODEL = "torchvision-resnet18-imagenet1k-v1"
IMAGE_VERSION = "avgpool512-rgb-exif-resize256-centercrop224-l2-v1"
EMBEDDING_DIMENSIONS = 512
WEIGHTS_SHA256 = "f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec"
_inference_lock = threading.Lock()
_download_slot = threading.BoundedSemaphore(1)


def normalise_vector(values, dimensions: int = EMBEDDING_DIMENSIONS) -> tuple[float, ...] | None:
    if values is None or isinstance(values, (str, bytes)):
        return None
    try:
        vector = tuple(float(value) for value in values)
        if len(vector) != dimensions or not all(isfinite(value) for value in vector):
            return None
        norm = sqrt(sum(value * value for value in vector))
        if not isfinite(norm) or norm <= 1e-12:
            return None
        return tuple(value / norm for value in vector)
    except (TypeError, ValueError, OverflowError):
        return None


def embedding_from_row(row: dict) -> ImageEmbedding | None:
    if (row.get("image_embedding_model") != IMAGE_MODEL
            or row.get("image_embedding_version") != IMAGE_VERSION
            or row.get("image_embedding_generated_at") is None):
        return None
    vector = normalise_vector(row.get("image_embedding"))
    return ImageEmbedding(row["evidence_id"], vector, IMAGE_MODEL, IMAGE_VERSION) if vector else None


def nearest_image_reports(source: ReportComparisonFacts, pool: list[ReportComparisonFacts], top_k: int = 10) -> dict[int, float]:
    """Exact KNN by cosine distance per source photo, then best pair per report.

    pool must already satisfy structural eligibility. More photos cannot sum
    contributions. A candidate outside top K can still match text/structure.
    """
    scores: dict[int, float] = {}
    history = []
    for report in pool:
        if report.report_id == source.report_id:
            continue
        for image in report.image_embeddings:
            if (image.model, image.version) != (IMAGE_MODEL, IMAGE_VERSION):
                continue
            vector = normalise_vector(image.vector)
            if vector is not None:
                history.append((report.report_id,image.evidence_id,vector))
    for query in source.image_embeddings:
        query_vector = normalise_vector(query.vector)
        if (query.model, query.version) != (IMAGE_MODEL, IMAGE_VERSION) or query_vector is None:
            continue
        neighbours = []
        for report_id,evidence_id,vector in history:
            cosine = max(-1.0, min(1.0, sum(a*b for a,b in zip(query_vector, vector))))
            neighbours.append((1-cosine, report_id, evidence_id))
        for distance, report_id, _ in sorted(neighbours)[:max(1, top_k)]:
            scores[report_id] = max(scores.get(report_id, 0.0), max(0.0, 1-distance))
    return scores


@lru_cache(maxsize=1)
def _load_model(weights_path: str):
    import torch
    from torchvision.models import ResNet18_Weights, resnet18

    path = Path(weights_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError("Pretrained image weights are not installed")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != WEIGHTS_SHA256:
        raise ValueError("Unexpected pretrained image weight checksum")
    torch.set_num_threads(1)
    model = resnet18(weights=None)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.fc = torch.nn.Identity()
    model.eval()
    return model, ResNet18_Weights.IMAGENET1K_V1.transforms()


def embed_image(content: bytes) -> tuple[float, ...]:
    """EXIF orientation, safe decoding, official preprocessing, pooled 512 features."""
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise ValueError("Image is empty or exceeds the evidence size limit")
    import torch
    from PIL import Image, ImageOps

    with _inference_lock, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported evidence image format")
            if original.width * original.height > settings.related_incident_image_max_pixels:
                raise ValueError("Image exceeds the decoded pixel limit")
            original.load()
            image = ImageOps.exif_transpose(original).convert("RGB")
            model, transform = _load_model(settings.related_incident_image_weights_path)
            with torch.inference_mode():
                output = model(transform(image).unsqueeze(0)).squeeze(0).tolist()
    vector = normalise_vector(output)
    if vector is None:
        raise ValueError("Image model produced invalid features")
    return vector


def _download_and_embed(file_reference: str) -> tuple[float, ...]:
    # Privileged system processing uses the server's private bucket, never a URL
    # supplied by a client. The database repository has selected eligible photos.
    # A timed-out download/thread may finish later. Avoid accumulating more
    # downloads while it is alive; the worker will retry on its next sweep.
    if not _download_slot.acquire(blocking=False):
        raise RuntimeError("Image worker is busy")
    try:
        content = _get_supabase_client().storage.from_(settings.supabase_storage_bucket).download(file_reference)
        return embed_image(content)
    finally:
        _download_slot.release()


async def generate_missing_embeddings(db: AsyncSession, rows: list[dict]) -> list[dict]:
    """Generate only this source report's missing/incompatible features.

    A failed image does not cancel other images or text matching. DB errors do
    propagate, since a failed transaction cannot safely continue. CPU/download
    work runs in a thread; a timeout abandons its result, with no late DB writes.
    """
    updated = [dict(row) for row in rows]
    for row in updated:
        if embedding_from_row(row) is not None:
            continue
        try:
            vector = await asyncio.wait_for(asyncio.to_thread(_download_and_embed, row["file_reference"]),
                                            timeout=settings.related_incident_image_timeout_seconds)
        except Exception as error:
            logger.warning("Image embedding unavailable for evidence %s (%s)", row["evidence_id"], type(error).__name__)
            continue
        saved = await repository.save_embedding(db, row["evidence_id"], row["file_reference"], vector, IMAGE_MODEL, IMAGE_VERSION)
        if saved:
            # Reload the actual DB timestamp/vector after committing in caller.
            row.update(image_embedding=vector, image_embedding_model=IMAGE_MODEL, image_embedding_version=IMAGE_VERSION)
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
