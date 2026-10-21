"""Exercise binary payload-file input without a shell/argv hex expansion."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: y4m_payload_file_smoke.py ENCODER INPUT_Y4M EXTRACTOR")
    encoder, input_y4m, extractor = map(Path, sys.argv[1:])
    payload = bytes.fromhex("5a4b5650010100000001112ebd16a5")

    with tempfile.TemporaryDirectory(prefix="zkstego-payload-file-") as temp_dir:
        temp = Path(temp_dir)
        payload_path = temp / "payload.bin"
        output_path = temp / "payload-file.h264"
        payload_path.write_bytes(payload)
        command = [
            str(encoder),
            "--input-y4m", str(input_y4m),
            "--output", str(output_path),
            "--payload-file", str(payload_path),
        ]
        embedded = subprocess.run(command, capture_output=True, text=True, check=False)
        if embedded.returncode != 0:
            raise SystemExit(
                f"payload-file encode failed ({embedded.returncode}): "
                f"{embedded.stderr.strip()}"
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise SystemExit("payload-file encode did not publish an H.264 output")

        extracted = subprocess.run(
            [sys.executable, str(extractor), str(output_path), "a5"],
            capture_output=True,
            text=True,
            check=False,
        )
        if extracted.returncode != 0:
            raise SystemExit(
                f"blind extraction failed ({extracted.returncode}): "
                f"{extracted.stderr.strip()}"
            )

        ambiguous = subprocess.run(
            command + ["--payload-hex", payload.hex()],
            capture_output=True,
            text=True,
            check=False,
        )
        if ambiguous.returncode == 0:
            raise SystemExit("encoder accepted mutually exclusive payload sources")

    print("PASS binary_payload_file_blind_extract=1 payload_sources_exclusive=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
