"""Export ResNet18 avgpool features to ONNX."""

import argparse
import hashlib

from pathlib import Path


WEIGHTS_SHA256 = (
    "f37072fd47e89c5e827621c5baffa750"
    "0819f7896bbacec160b1a16c560e07ec"
)


def sha256_file(
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


def export_onnx(
    weights_path: Path,
    output_path: Path,
):

    import torch

    from torchvision.models import (
        resnet18,
    )

    if not weights_path.is_file():

        raise FileNotFoundError(
            f"Missing weights: "
            f"{weights_path}"
        )

    if (
        sha256_file(
            weights_path
        )
        != WEIGHTS_SHA256
    ):
        raise ValueError(
            "Unexpected ResNet18 "
            "weight checksum"
        )

    model = resnet18(
        weights=None
    )

    model.load_state_dict(
        torch.load(
            weights_path,
            map_location="cpu",
            weights_only=True,
        )
    )

    # Return 512-dimensional avgpool features
    # instead of ImageNet classification logits.
    model.fc = torch.nn.Identity()

    model.eval()

    dummy = torch.zeros(
        1,
        3,
        224,
        224,
        dtype=torch.float32,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    torch.onnx.export(
        model,
        dummy,
        str(output_path),
        input_names=["input"],
        output_names=["embedding"],
        dynamic_axes={
            "input": {
                0: "batch"
            },
            "embedding": {
                0: "batch"
            },
        },
        opset_version=18,
        do_constant_folding=True,
        dynamo=False,
    )

    digest = sha256_file(
        output_path
    )

    checksum_path = (
        output_path.with_suffix(
            output_path.suffix
            + ".sha256"
        )
    )

    checksum_path.write_text(
        digest + "\n",
        encoding="utf-8",
    )

    print(
        f"Exported: {output_path}"
    )

    print(
        f"SHA256: {digest}"
    )


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--weights",
        type=Path,
        default=Path(
            "models/"
            "resnet18-f37072fd.pth"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "models/"
            "resnet18-avgpool512.onnx"
        ),
    )

    args = parser.parse_args()

    export_onnx(
        args.weights,
        args.output,
    )
