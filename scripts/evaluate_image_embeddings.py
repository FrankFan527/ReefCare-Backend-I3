import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]

MODEL = ROOT / "models/resnet18-avgpool512.onnx"
DATASET = ROOT / "tests/evaluation/us59_scenarios.json"

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
    image_path = resolve_image_path(path)

    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")

    width, height = image.size

    if width < height:
        new_width = 256
        new_height = round(height * 256 / width)
    else:
        new_height = 256
        new_width = round(width * 256 / height)

    image = image.resize(
        (new_width, new_height),
        Image.Resampling.BILINEAR,
    )

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
        np.asarray(image, dtype=np.float32)
        / 255.0
    )

    array = (array - MEAN) / STD

    array = np.transpose(
        array,
        (2, 0, 1),
    )

    return array[np.newaxis, ...]


def embedding(
    session: ort.InferenceSession,
    path: str,
) -> np.ndarray:

    input_name = session.get_inputs()[0].name

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

    if vector.shape != (512,):
        raise AssertionError(
            f"{path}: expected 512 values, "
            f"got {vector.shape}"
        )

    if not np.isfinite(vector).all():
        raise AssertionError(
            f"{path}: embedding contains NaN/Inf"
        )

    norm = np.linalg.norm(vector)

    if norm == 0:
        raise AssertionError(
            f"{path}: zero embedding"
        )

    return vector / norm


def cosine(a, b):
    return float(np.dot(a, b))


def safe_div(a, b):
    return a / b if b else 0.0


def main():
    dataset = json.loads(
        DATASET.read_text()
    )

    threshold = float(
        dataset.get(
            "imageThreshold",
            0.80,
        )
    )

    session = ort.InferenceSession(
        str(MODEL),
        providers=[
            "CPUExecutionProvider"
        ],
    )

    cache = {}

    def get(path):
        if path not in cache:
            cache[path] = embedding(
                session,
                path,
            )

        return cache[path]

    tp = fp = tn = fn = 0
    evaluated = 0

    print("\nEmbedding validation\n")
    print(f"Threshold: {threshold:.2f}\n")

    for scenario in dataset["scenarios"]:

        path_a = scenario.get(
            "source_image"
        )

        path_b = scenario.get(
            "candidate_image"
        )

        expected = scenario.get(
            "expected_image_similar"
        )

        # Scenario intentionally has no image evaluation.
        if (
            not path_a
            or not path_b
            or expected is None
        ):
            print(
                f"{scenario['id']:4} SKIPPED "
                f"(no image evaluation configured)"
            )
            continue

        evaluated += 1

        a = get(path_a)
        b = get(path_b)

        score = cosine(a, b)

        predicted = (
            score >= threshold
        )

        if expected and predicted:
            result = "TP"
            tp += 1

        elif not expected and predicted:
            result = "FP"
            fp += 1

        elif not expected and not predicted:
            result = "TN"
            tn += 1

        else:
            result = "FN"
            fn += 1

        print(
            f"{scenario['id']:4} "
            f"cosine={score:.4f} "
            f"expected={str(expected):5} "
            f"predicted={str(predicted):5} "
            f"{result}"
        )

    print("\nStructural checks")

    for path, vector in cache.items():
        print(
            f"{path}: "
            f"shape={vector.shape}, "
            f"norm={np.linalg.norm(vector):.6f}, "
            f"finite={np.isfinite(vector).all()}"
        )

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
        2 * precision * recall
        / (precision + recall)
        if precision + recall
        else 0.0
    )

    print("\nImage similarity metrics")
    print(f"Evaluated pairs: {evaluated}")
    print(
        f"TP={tp} FP={fp} "
        f"FN={fn} TN={tn}"
    )
    print(
        f"Precision: {precision:.3f}"
    )
    print(
        f"Recall:    {recall:.3f}"
    )
    print(
        f"F1:        {f1:.3f}"
    )
    print(
        f"Accuracy:  {accuracy:.3f}"
    )


if __name__ == "__main__":
    main()