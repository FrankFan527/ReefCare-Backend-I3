import sys
import asyncio
import json

from dataclasses import (
    MISSING,
    fields,
    replace,
)
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


# ---------------------------------------------------------------------------
# Make app/ importable when running:
#
#   python scripts/evaluate_related_incident.py
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.schemas.related_incident import (
    ImageEmbedding,
    ReportComparisonFacts,
)

from app.services.related_incident_detection_service import (
    MatchingRules,
    match_related_reports,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATASET = (
    ROOT
    / "tests"
    / "evaluation"
    / "us59_scenarios.json"
)

MODEL = (
    ROOT
    / "models"
    / "resnet18-avgpool512.onnx"
)


# ---------------------------------------------------------------------------
# Image embedding metadata
#
# Keep these consistent with the model/version stored by your actual
# embedding implementation.
# ---------------------------------------------------------------------------

IMAGE_MODEL = (
    "torchvision-resnet18-imagenet1k-v1"
)

IMAGE_VERSION = (
    "avgpool512-rgb-exif-resize256-"
    "centercrop224-l2-v1"
)


# ---------------------------------------------------------------------------
# ResNet preprocessing
# ---------------------------------------------------------------------------

MEAN = np.array(
    [0.485, 0.456, 0.406],
    dtype=np.float32,
)

STD = np.array(
    [0.229, 0.224, 0.225],
    dtype=np.float32,
)


def resolve_image_path(path: str) -> Path:
    image_path = Path(path)

    if not image_path.is_absolute():
        image_path = ROOT / image_path

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    return image_path


def preprocess(path: str) -> np.ndarray:
    """
    Convert image to ResNet18 ImageNet input.

    Output shape:
        (1, 3, 224, 224)
    """

    image_path = resolve_image_path(path)

    image = Image.open(image_path)

    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    width, height = image.size

    # Resize shortest side to 256 while keeping aspect ratio.
    if width < height:
        new_width = 256
        new_height = round(
            height * 256 / width
        )
    else:
        new_height = 256
        new_width = round(
            width * 256 / height
        )

    image = image.resize(
        (new_width, new_height),
        Image.Resampling.BILINEAR,
    )

    # Center crop 224 x 224.
    left = (new_width - 224) // 2
    top = (new_height - 224) // 2

    image = image.crop(
        (
            left,
            top,
            left + 224,
            top + 224,
        )
    )

    array = (
        np.asarray(
            image,
            dtype=np.float32,
        )
        / 255.0
    )

    # ImageNet normalisation.
    array = (
        array - MEAN
    ) / STD

    # HWC -> CHW
    array = np.transpose(
        array,
        (2, 0, 1),
    )

    # CHW -> NCHW
    return array[np.newaxis, ...]


# ---------------------------------------------------------------------------
# ONNX embedding
# ---------------------------------------------------------------------------

def generate_embedding(
    session: ort.InferenceSession,
    path: str,
) -> np.ndarray:

    input_name = (
        session
        .get_inputs()[0]
        .name
    )

    output = session.run(
        None,
        {
            input_name: preprocess(path),
        },
    )[0]

    vector = np.asarray(
        output,
        dtype=np.float32,
    ).reshape(-1)

    # Your exported model should return the 512-dimensional
    # ResNet18 avgpool representation.
    if vector.shape != (512,):
        raise AssertionError(
            f"{path}: expected embedding "
            f"shape (512,), got "
            f"{vector.shape}"
        )

    if not np.isfinite(vector).all():
        raise AssertionError(
            f"{path}: embedding contains "
            f"NaN or Inf"
        )

    norm = np.linalg.norm(vector)

    if norm == 0:
        raise AssertionError(
            f"{path}: generated zero vector"
        )

    # L2 normalise.
    vector = vector / norm

    return vector


def cosine_similarity(
    first: np.ndarray,
    second: np.ndarray,
) -> float:
    """
    Because vectors are already L2 normalised,
    dot product == cosine similarity.
    """

    return float(
        np.dot(
            first,
            second,
        )
    )


# ---------------------------------------------------------------------------
# Build ImageEmbedding
#
# Your ReportComparisonFacts field is:
#
#     image_embeddings:
#         tuple[ImageEmbedding, ...]
#
# This helper supports the common field names used by the current model.
# ---------------------------------------------------------------------------

def build_image_embedding(
    vector: np.ndarray,
    evidence_id: int,
) -> ImageEmbedding:

    vector_tuple = tuple(
        float(value)
        for value in vector
    )

    values = {}

    for field in fields(ImageEmbedding):
        name = field.name

        if name in {
            "evidence_id",
            "image_id",
        }:
            values[name] = evidence_id

        elif name in {
            "embedding",
            "image_embedding",
            "vector",
            "values",
        }:
            values[name] = vector_tuple

        elif name in {
            "model",
            "model_name",
            "embedding_model",
            "image_embedding_model",
        }:
            values[name] = IMAGE_MODEL

        elif name in {
            "version",
            "embedding_version",
            "image_embedding_version",
        }:
            values[name] = IMAGE_VERSION

        elif name in {
            "generated_at",
            "embedding_generated_at",
            "image_embedding_generated_at",
        }:
            values[name] = datetime.now(
                timezone.utc
            )

        # Leave fields with defaults alone.
        elif field.default is not MISSING:
            continue

        elif (
            field.default_factory
            is not MISSING
        ):
            continue

        else:
            raise RuntimeError(
                "Unsupported required "
                "ImageEmbedding field: "
                f"{name!r}\n"
                "\nRun:\n"
                "PYTHONPATH=. python - <<'PY'\n"
                "from dataclasses import fields\n"
                "from "
                "app.schemas.related_incident "
                "import ImageEmbedding\n"
                "for f in fields(ImageEmbedding):\n"
                "    print(f.name, f.type)\n"
                "PY"
            )

    return ImageEmbedding(
        **values
    )


# ---------------------------------------------------------------------------
# Parse JSON report into ReportComparisonFacts
# ---------------------------------------------------------------------------

def parse_report(
    data: dict,
) -> ReportComparisonFacts:

    values = dict(data)

    if values.get("observed_at"):
        values["observed_at"] = (
            datetime.fromisoformat(
                values["observed_at"]
                .replace(
                    "Z",
                    "+00:00",
                )
            )
        )

    decimal_fields = (
        "estimated_depth_metres",
        "generalised_latitude",
        "generalised_longitude",
    )

    for field_name in decimal_fields:
        if (
            values.get(field_name)
            is not None
        ):
            values[field_name] = Decimal(
                str(
                    values[field_name]
                )
            )

    return ReportComparisonFacts(
        **values
    )


def safe_div(
    numerator: int,
    denominator: int,
) -> float:

    if denominator == 0:
        return 0.0

    return (
        numerator
        / denominator
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

async def main():

    # -----------------------------------------------------------------------
    # Load evaluation set
    # -----------------------------------------------------------------------

    dataset = json.loads(
        DATASET.read_text()
    )

    # -----------------------------------------------------------------------
    # Use ACTUAL matching configuration.
    #
    # This means thresholds are not duplicated in this script.
    # -----------------------------------------------------------------------

    rules = MatchingRules()

    print(
        "\nUS5.9 configuration\n"
    )

    print(
        f"Minimum score:       "
        f"{rules.minimum_score}"
    )

    print(
        f"Medium threshold:    "
        f"{rules.medium_score}"
    )

    print(
        f"High threshold:      "
        f"{rules.high_score}"
    )

    print(
        f"Image threshold:     "
        f"{rules.image_threshold}"
    )

    print(
        f"Images enabled:      "
        f"{rules.images_enabled}"
    )

    print(
        f"Window days:         "
        f"{rules.window_days}"
    )

    print(
        f"Nearby metres:       "
        f"{rules.nearby_metres}"
    )

    # -----------------------------------------------------------------------
    # ONNX model
    # -----------------------------------------------------------------------

    if not MODEL.exists():
        raise FileNotFoundError(
            f"ONNX model not found: "
            f"{MODEL}"
        )

    session = ort.InferenceSession(
        str(MODEL),
        providers=[
            "CPUExecutionProvider",
        ],
    )

    embedding_cache = {}

    def get_embedding(
        path: str,
    ) -> np.ndarray:

        if (
            path
            not in embedding_cache
        ):
            embedding_cache[path] = (
                generate_embedding(
                    session,
                    path,
                )
            )

        return (
            embedding_cache[path]
        )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    tp = 0
    fp = 0
    tn = 0
    fn = 0

    level_correct = 0
    level_total = 0

    # Optional image-signal diagnostics.
    image_tp = 0
    image_fp = 0
    image_tn = 0
    image_fn = 0

    rows = []

    # -----------------------------------------------------------------------
    # Evaluate scenarios
    # -----------------------------------------------------------------------

    for index, scenario in enumerate(
        dataset["scenarios"],
        start=1,
    ):

        source = parse_report(
            scenario["source"]
        )

        candidate = parse_report(
            scenario["candidate"]
        )

        source_image = (
            scenario.get(
                "source_image"
            )
        )

        candidate_image = (
            scenario.get(
                "candidate_image"
            )
        )

        source_vector = None
        candidate_vector = None
        image_cosine = None

        # -------------------------------------------------------------------
        # Attach image embeddings
        # -------------------------------------------------------------------

        if source_image:
            source_vector = (
                get_embedding(
                    source_image
                )
            )

            source_embedding = (
                build_image_embedding(
                    source_vector,
                    evidence_id=(
                        100000
                        + index * 2
                    ),
                )
            )

            source = replace(
                source,
                image_embeddings=(
                    source_embedding,
                ),
            )

        if candidate_image:
            candidate_vector = (
                get_embedding(
                    candidate_image
                )
            )

            candidate_embedding = (
                build_image_embedding(
                    candidate_vector,
                    evidence_id=(
                        100000
                        + index * 2
                        + 1
                    ),
                )
            )

            candidate = replace(
                candidate,
                image_embeddings=(
                    candidate_embedding,
                ),
            )

        if (
            source_vector
            is not None
            and candidate_vector
            is not None
        ):
            image_cosine = (
                cosine_similarity(
                    source_vector,
                    candidate_vector,
                )
            )

        # -------------------------------------------------------------------
        # Run ACTUAL US5.9 matcher.
        #
        # No DB.
        # No repository.
        # No run persistence.
        # -------------------------------------------------------------------

        outcome = (
            await match_related_reports(
                source,
                [candidate],
                rules,
            )
        )

        predicted_related = bool(
            outcome.candidates
        )

        match = (
            outcome.candidates[0]
            if outcome.candidates
            else None
        )

        # -------------------------------------------------------------------
        # Ground truth
        # -------------------------------------------------------------------

        expected_related = (
            scenario[
                "expected_related"
            ]
        )

        expected_level = (
            scenario.get(
                "expected_level"
            )
        )

        expected_image_similar = (
            scenario.get(
                "expected_image_similar"
            )
        )

        # -------------------------------------------------------------------
        # Actual level
        # -------------------------------------------------------------------

        actual_level = (
            match.relatedness_level.value
            if match
            else None
        )

        # -------------------------------------------------------------------
        # Final related/not-related metrics
        # -------------------------------------------------------------------

        if (
            expected_related
            and predicted_related
        ):
            tp += 1
            classification = "TP"

        elif (
            not expected_related
            and predicted_related
        ):
            fp += 1
            classification = "FP"

        elif (
            not expected_related
            and not predicted_related
        ):
            tn += 1
            classification = "TN"

        else:
            fn += 1
            classification = "FN"

        # -------------------------------------------------------------------
        # Relatedness level metrics
        # -------------------------------------------------------------------

        level_result = None

        if (
            expected_related
            and expected_level
            is not None
        ):
            level_total += 1

            if (
                actual_level
                == expected_level
            ):
                level_correct += 1
                level_result = "PASS"

            else:
                level_result = "FAIL"

        # -------------------------------------------------------------------
        # Image-only metrics
        #
        # IMPORTANT:
        # This is diagnostic only.
        # The full matcher remains authoritative.
        # -------------------------------------------------------------------

        image_predicted = None
        image_result = None

        if (
            image_cosine is not None
            and expected_image_similar
            is not None
        ):
            image_predicted = (
                image_cosine
                >= rules.image_threshold
            )

            if (
                expected_image_similar
                and image_predicted
            ):
                image_tp += 1
                image_result = "TP"

            elif (
                not expected_image_similar
                and image_predicted
            ):
                image_fp += 1
                image_result = "FP"

            elif (
                not expected_image_similar
                and not image_predicted
            ):
                image_tn += 1
                image_result = "TN"

            else:
                image_fn += 1
                image_result = "FN"

        # -------------------------------------------------------------------
        # Signals
        # -------------------------------------------------------------------

        signal_codes = (
            [
                signal.code
                for signal
                in match.signals
            ]
            if match
            else []
        )

        has_image_signal = (
            "similar_image"
            in signal_codes
        )

        rows.append(
            {
                "scenario":
                    scenario["id"],

                "expected":
                    expected_related,

                "predicted":
                    predicted_related,

                "result":
                    classification,

                "expected_level":
                    expected_level,

                "actual_level":
                    actual_level,

                "level_result":
                    level_result,

                "score":
                    (
                        float(
                            match
                            .similarity_score
                        )
                        if match
                        else None
                    ),

                "image_cosine":
                    image_cosine,

                "expected_image_similar":
                    expected_image_similar,

                "image_predicted":
                    image_predicted,

                "image_result":
                    image_result,

                "has_image_signal":
                    has_image_signal,

                "signals":
                    signal_codes,
            }
        )

    # -----------------------------------------------------------------------
    # Final binary metrics
    # -----------------------------------------------------------------------

    precision = safe_div(
        tp,
        tp + fp,
    )

    recall = safe_div(
        tp,
        tp + fn,
    )

    accuracy = safe_div(
        tp + tn,
        tp + tn + fp + fn,
    )

    f1 = (
        2
        * precision
        * recall
        / (
            precision
            + recall
        )
        if (
            precision
            + recall
        )
        else 0.0
    )

    # -----------------------------------------------------------------------
    # Relatedness level accuracy
    # -----------------------------------------------------------------------

    level_accuracy = safe_div(
        level_correct,
        level_total,
    )

    # -----------------------------------------------------------------------
    # Image-only metrics
    # -----------------------------------------------------------------------

    image_precision = safe_div(
        image_tp,
        image_tp + image_fp,
    )

    image_recall = safe_div(
        image_tp,
        image_tp + image_fn,
    )

    image_accuracy = safe_div(
        image_tp + image_tn,
        (
            image_tp
            + image_tn
            + image_fp
            + image_fn
        ),
    )

    image_f1 = (
        2
        * image_precision
        * image_recall
        / (
            image_precision
            + image_recall
        )
        if (
            image_precision
            + image_recall
        )
        else 0.0
    )

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------

    print(
        "\nUS5.9 scenario results\n"
    )

    for row in rows:

        image_cosine_text = (
            f"{row['image_cosine']:.4f}"
            if (
                row["image_cosine"]
                is not None
            )
            else "None"
        )

        print(
            f"{row['scenario']:4} "
            f"expected="
            f"{str(row['expected']):5} "
            f"predicted="
            f"{str(row['predicted']):5} "
            f"{row['result']:2} "
            f"expectedLevel="
            f"{row['expected_level']} "
            f"actualLevel="
            f"{row['actual_level']} "
            f"score="
            f"{row['score']} "
            f"imageCosine="
            f"{image_cosine_text} "
            f"imageSignal="
            f"{row['has_image_signal']} "
            f"signals="
            f"{row['signals']}"
        )

    # -----------------------------------------------------------------------
    # Confusion matrix
    # -----------------------------------------------------------------------

    print(
        "\nConfusion matrix"
    )

    print(
        f"TP={tp} FP={fp}"
    )

    print(
        f"FN={fn} TN={tn}"
    )

    print(
        "\nDetection metrics"
    )

    print(
        f"Precision: "
        f"{precision:.3f}"
    )

    print(
        f"Recall:    "
        f"{recall:.3f}"
    )

    print(
        f"F1:        "
        f"{f1:.3f}"
    )

    print(
        f"Accuracy:  "
        f"{accuracy:.3f}"
    )

    # -----------------------------------------------------------------------
    # Relatedness classification
    # -----------------------------------------------------------------------

    print(
        "\nRelatedness classification"
    )

    print(
        f"Level accuracy: "
        f"{level_accuracy:.3f} "
        f"({level_correct}/"
        f"{level_total})"
    )

    print(
        "\nRelatedness level details"
    )

    for row in rows:

        if (
            row["expected_level"]
            is None
        ):
            continue

        print(
            f"{row['scenario']}: "
            f"expected="
            f"{row['expected_level']} "
            f"actual="
            f"{row['actual_level']} "
            f"[{row['level_result']}]"
        )

    # -----------------------------------------------------------------------
    # Image diagnostics
    # -----------------------------------------------------------------------

    print(
        "\nImage signal details"
    )

    for row in rows:

        if (
            row[
                "expected_image_similar"
            ]
            is None
        ):
            continue

        cosine_text = (
            f"{row['image_cosine']:.4f}"
            if (
                row["image_cosine"]
                is not None
            )
            else "None"
        )

        print(
            f"{row['scenario']}: "
            f"cosine="
            f"{cosine_text} "
            f"expected="
            f"{row['expected_image_similar']} "
            f"predicted="
            f"{row['image_predicted']} "
            f"imageSignal="
            f"{row['has_image_signal']} "
            f"[{row['image_result']}]"
        )

    print(
        "\nImage-only metrics"
    )

    print(
        f"TP={image_tp} "
        f"FP={image_fp} "
        f"FN={image_fn} "
        f"TN={image_tn}"
    )

    print(
        f"Precision: "
        f"{image_precision:.3f}"
    )

    print(
        f"Recall:    "
        f"{image_recall:.3f}"
    )

    print(
        f"F1:        "
        f"{image_f1:.3f}"
    )

    print(
        f"Accuracy:  "
        f"{image_accuracy:.3f}"
    )

    # -----------------------------------------------------------------------
    # Structural embedding validation
    # -----------------------------------------------------------------------

    print(
        "\nEmbedding structural checks"
    )

    for path, vector in (
        embedding_cache.items()
    ):

        print(
            f"{path}: "
            f"shape="
            f"{vector.shape}, "
            f"norm="
            f"{np.linalg.norm(vector):.6f}, "
            f"finite="
            f"{np.isfinite(vector).all()}"
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )