"""Compare native CAVLC carrier normalization for two equal-length payloads.

The input videos must be two separate native x264 encodes of the same Y4M
cover, with the same encoder settings and application payload byte length.
This is a diagnostic of the current encoder, not a proof of video binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from native.x264_fork.tests.blind_extract_smoke import extract_payload_with_positions
from src.manifest import hash_positions
from src.video_canonicalization import canonical_video_sha256


def inspect_video(path: Path, expected_payload: bytes) -> tuple[dict[str, object], tuple[tuple[int, int, int], ...]]:
    source = path.resolve(strict=True)
    payload, positions = extract_payload_with_positions(source, include_p_slices=False)
    if payload != expected_payload:
        raise ValueError(f"blind payload mismatch for {source}")
    with source.open("rb") as stream:
        raw_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "video": str(source),
        "video_bytes": source.stat().st_size,
        "raw_sha256": raw_digest,
        "payload_hex": payload.hex(),
        "carrier_count": len(positions),
        "positions_hash": hash_positions(positions),
        "canonical_video_sha256": canonical_video_sha256(source, positions),
    }, positions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_video", type=Path)
    parser.add_argument("second_video", type=Path)
    parser.add_argument("--first-payload-hex", required=True)
    parser.add_argument("--second-payload-hex", required=True)
    args = parser.parse_args()

    first, first_positions = inspect_video(
        args.first_video, bytes.fromhex(args.first_payload_hex)
    )
    second, second_positions = inspect_video(
        args.second_video, bytes.fromhex(args.second_payload_hex)
    )
    first_difference = next(
        (
            index
            for index, (left, right) in enumerate(zip(first_positions, second_positions))
            if left != right
        ),
        None,
    )
    if first_difference is None and len(first_positions) != len(second_positions):
        first_difference = min(len(first_positions), len(second_positions))
    report = {
        "schema": "native-carrier-normalization-probe-v1",
        "first": first,
        "second": second,
        "same_carrier_positions": first_positions == second_positions,
        "first_differing_carrier_index": first_difference,
        "same_canonical_video_sha256": (
            first["canonical_video_sha256"] == second["canonical_video_sha256"]
        ),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
