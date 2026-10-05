"""Download the official ResNet18 weights once, before starting the worker."""
import argparse
import hashlib
from pathlib import Path
import ssl
import urllib.request

URL = "https://download.pytorch.org/models/resnet18-f37072fd.pth"
SHA256 = "f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec"


def main(output: Path):
    if output.is_file() and hashlib.sha256(output.read_bytes()).hexdigest() == SHA256:
        print(f"Verified existing model: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    # Verify HTTPS certificates using the same CA bundle as the backend client.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    temporary = output.with_suffix(".download")
    try:
        with urllib.request.urlopen(URL, context=context, timeout=60) as response, temporary.open("wb") as target:
            while chunk := response.read(1024*1024):
                target.write(chunk)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != SHA256:
            raise ValueError("Official model checksum does not match")
        temporary.replace(output)
        print(f"Downloaded and verified model: {output} ({digest})")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("models/resnet18-f37072fd.pth"))
    main(parser.parse_args().output)
