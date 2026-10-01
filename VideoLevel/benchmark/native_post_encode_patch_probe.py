"""Test whether the existing CAVLC patcher can replace native payload bits.

This is an isolated diagnostic. It does not publish a proof-bearing video or
define a security protocol. The target is an equal-length application payload.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from native.x264_fork.tests.blind_extract_smoke import extract_payload_with_positions
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser
from src.blind_sync import pack_blind_payload
from src.core.pipeline import extract_all_idr_blocks
from src.video_canonicalization import canonical_video_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("target_payload_hex")
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    output = args.output.resolve(strict=False)
    if output.exists():
        parser.error("output path must not exist")
    target_payload = bytes.fromhex(args.target_payload_hex)
    original_payload, original_positions = extract_payload_with_positions(
        source, include_p_slices=False
    )
    if len(target_payload) != len(original_payload):
        parser.error("target application payload must have the original length")
    framed_target = pack_blind_payload(target_payload)
    if len(original_positions) != len(framed_target) * 8:
        raise ValueError("carrier count does not match the framed target")

    nal_parser = H264BitstreamParser(str(source))
    nal_parser.parse()
    reconstructor = BitstreamReconstructor()
    _, frame_data, _, _, _ = extract_all_idr_blocks(
        str(source), reconstructor, parser=nal_parser
    )
    blocks = {
        key: coefficients
        for _, frame_blocks, _ in frame_data.values()
        for key, coefficients in frame_blocks.items()
    }
    changed_blocks: dict[tuple[int, int], list[int]] = {}
    for bit_index, (macroblock, block, coefficient_index) in enumerate(original_positions):
        target_bit = (framed_target[bit_index // 8] >> (7 - bit_index % 8)) & 1
        key = (macroblock, block)
        original_levels = blocks[key]
        value = original_levels[coefficient_index]
        if abs(value) < 5:
            raise ValueError(f"native carrier lost eligibility at {key}")
        if (abs(value) & 1) == target_bit:
            continue
        modified_levels = changed_blocks.setdefault(key, list(original_levels))
        modified_levels[coefficient_index] += -1 if value < 0 else 1

    modifications = [
        (macroblock, block, levels)
        for (macroblock, block), levels in sorted(changed_blocks.items())
    ]
    started = perf_counter()
    stats = reconstructor.reconstruct_video(
        str(source), modifications, str(output), max_slices=None,
        frame_verified_data=frame_data,
    )
    elapsed = perf_counter() - started
    skipped = stats.get("skipped_block_reasons", {})
    serializable_stats = {
        **stats,
        "skipped_block_reasons": {str(key): reason for key, reason in skipped.items()},
    }
    report: dict[str, object] = {
        "source": str(source),
        "output": str(output),
        "original_payload_hex": original_payload.hex(),
        "target_payload_hex": target_payload.hex(),
        "requested_block_changes": len(modifications),
        "patch_wall_seconds": elapsed,
        "patch_stats": serializable_stats,
    }
    if output.is_file():
        try:
            extracted, patched_positions = extract_payload_with_positions(
                output, include_p_slices=False
            )
            report["blind_extracted_payload_hex"] = extracted.hex()
            report["blind_target_match"] = extracted == target_payload
            report["same_positions"] = patched_positions == original_positions
            report["canonical_digest_before"] = canonical_video_sha256(
                source, original_positions
            )
            report["canonical_digest_after"] = canonical_video_sha256(
                output, patched_positions
            )
            report["same_canonical_digest"] = (
                report["canonical_digest_before"] == report["canonical_digest_after"]
            )
        except (RuntimeError, ValueError) as error:
            report["blind_or_digest_error"] = str(error)
    print(json.dumps(report, indent=2))
    return 0 if report.get("blind_target_match") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
