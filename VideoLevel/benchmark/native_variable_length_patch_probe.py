"""Research-only variable-length CAVLC replacement on a native H.264 cover.

Use a native video carrying a small placeholder payload. This diagnostic
replaces selected CAVLC block codewords after encoding, then checks whether
the blind extractor recovers a same-length replacement payload. It is not the
validated production patcher or a realtime implementation.
"""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from native.x264_fork.tests.blind_extract_smoke import extract_payload_with_positions
from src.bitstream.bitstream_io import BitstreamReader
from src.bitstream.bitstream_ops import BitstreamPatcher, BitstreamReconstructor
from src.bitstream.cavlc import CAVLCDecoder
from src.bitstream.h264 import H264BitstreamParser
from src.blind_sync import pack_blind_payload
from src.core.pipeline import extract_all_idr_blocks
from src.video_canonicalization import canonical_video_sha256


def syntax_bit_length(rbsp: bytes) -> int:
    """Return the bit length through rbsp_stop_one_bit, excluding pad zeros."""
    for byte_index in range(len(rbsp) - 1, -1, -1):
        value = rbsp[byte_index]
        if value:
            trailing_zeros = (value & -value).bit_length() - 1
            return byte_index * 8 + 8 - trailing_zeros
    raise ValueError("RBSP has no stop bit")


def replace_codewords(
    source: Path,
    output: Path,
    framed_target: bytes,
    positions: tuple[tuple[int, int, int], ...],
) -> dict[str, object]:
    parser = H264BitstreamParser(str(source))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    _, frames, _, _, _ = extract_all_idr_blocks(
        str(source), reconstructor, parser=parser
    )
    frame_offsets = sorted(frames)
    patcher = BitstreamPatcher()
    changes_by_frame: dict[int, list[tuple[int, int, list[int]]]] = {}
    requested_changes = 0
    for bit_index, (macroblock, block, coefficient_index) in enumerate(positions):
        target_bit = (framed_target[bit_index // 8] >> (7 - bit_index % 8)) & 1
        candidate_index = bisect_right(frame_offsets, macroblock) - 1
        if candidate_index < 0:
            raise ValueError("carrier has no containing IDR frame")
        frame_offset = frame_offsets[candidate_index]
        offsets, blocks, _ = frames[frame_offset]
        key = (macroblock, block)
        if key not in offsets or key not in blocks:
            raise ValueError(f"carrier is absent from parsed IDR block {key}")
        original = blocks[key]
        magnitude = abs(original[coefficient_index])
        if magnitude < 5:
            raise ValueError(f"ineligible native carrier {key}")
        if (magnitude & 1) == target_bit:
            continue
        modified = list(original)
        # Pair (5, 6), (7, 8), ... so either parity maps to the same
        # native_odd_anchor_v1 normalized coefficient.
        magnitude_delta = 1 if magnitude & 1 else -1
        modified[coefficient_index] += (
            -magnitude_delta if original[coefficient_index] < 0 else magnitude_delta
        )
        changes_by_frame.setdefault(frame_offset, []).append(
            (macroblock, block, modified)
        )
        requested_changes += 1

    new_nals = []
    idr_index = 0
    new_bit_lengths: list[int] = []
    for nal in parser.nal_units:
        if int(nal.nal_unit_type) != 5:
            new_nals.append(nal)
            continue
        frame_offset = frame_offsets[idr_index]
        idr_index += 1
        replacements = []
        offsets, _, original_rbsp = frames[frame_offset]
        if bytes(nal.rbsp_byte) != bytes(original_rbsp):
            raise ValueError("IDR parser and frame data disagree")
        for macroblock, block, modified in changes_by_frame.get(frame_offset, []):
            info = offsets[(macroblock, block)]
            n_c = info.get("validated_nC", info.get("nC"))
            if n_c is None:
                raise ValueError("missing CAVLC neighbor context")
            max_coeff = info.get("max_num_coeff", 16)
            new_bits = patcher._encode_coefficients_to_bits(modified, n_c, max_coeff)
            decoded = CAVLCDecoder(
                BitstreamReader(patcher._bits_to_bytes(new_bits + [0] * 64))
            )
            # Validate each replacement before modifying the H.264 stream.
            reader = decoded.reader
            decoded_block = decoded.decode_block_cavlc(n_c, max_num_coeff=max_coeff)
            if reader.pos != len(new_bits) or list(decoded_block.levels) != modified:
                raise ValueError(f"CAVLC replacement did not round-trip: {(macroblock, block)}")
            start = info["start_bit"]
            end = info["end_bit"]
            if not 0 <= start < end <= syntax_bit_length(original_rbsp):
                raise ValueError("invalid CAVLC codeword bit range")
            replacements.append((start, end, new_bits))
            new_bit_lengths.append(len(new_bits) - (end - start))
        if not replacements:
            new_nals.append(nal)
            continue
        bits = np.unpackbits(np.frombuffer(bytes(nal.rbsp_byte), dtype=np.uint8)).tolist()
        bits = bits[: syntax_bit_length(bytes(nal.rbsp_byte))]
        for start, end, new_bits in sorted(replacements, reverse=True):
            bits[start:end] = new_bits
        bits.extend([0] * ((-len(bits)) % 8))
        new_rbsp = np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()
        new_nals.append(
            SimpleNamespace(
                forbidden_zero_bit=nal.forbidden_zero_bit,
                nal_ref_idc=nal.nal_ref_idc,
                nal_unit_type=nal.nal_unit_type,
                rbsp_byte=new_rbsp,
                start_code_size=nal.start_code_size,
            )
        )
    if idr_index != len(frame_offsets):
        raise ValueError("IDR frame count changed during rewrite")
    reconstructor._write_h264_file(new_nals, str(output))
    return {
        "requested_changes": requested_changes,
        "changed_nals": len(changes_by_frame),
        "codeword_bit_length_delta_min": min(new_bit_lengths, default=0),
        "codeword_bit_length_delta_max": max(new_bit_lengths, default=0),
        "output_bytes": output.stat().st_size,
    }


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("target_payload_hex")
    args = cli.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve(strict=False)
    if output.exists():
        cli.error("output path must not exist")
    target = bytes.fromhex(args.target_payload_hex)
    original, positions = extract_payload_with_positions(
        source, include_p_slices=False
    )
    if len(original) != len(target):
        cli.error("target payload must have the same application byte length")
    framed = pack_blind_payload(target)
    if len(positions) != len(framed) * 8:
        raise ValueError("carrier prefix length does not match target envelope")
    started = perf_counter()
    patch_stats = replace_codewords(source, output, framed, positions)
    patched, patched_positions = extract_payload_with_positions(
        output, include_p_slices=False
    )
    report = {
        "normalization_profile": "native_odd_anchor_v1",
        "original_payload_hex": original.hex(),
        "target_payload_hex": target.hex(),
        "blind_extracted_payload_hex": patched.hex(),
        "blind_target_match": patched == target,
        "same_carrier_positions": patched_positions == positions,
        "canonical_digest_before": canonical_video_sha256(
            source, positions, magnitude_pair="native_odd_anchor_v1"
        ),
        "canonical_digest_after": canonical_video_sha256(
            output, patched_positions, magnitude_pair="native_odd_anchor_v1"
        ),
        "patch_stats": patch_stats,
        "total_wall_seconds": perf_counter() - started,
    }
    report["same_canonical_digest"] = (
        report["canonical_digest_before"] == report["canonical_digest_after"]
    )
    print(json.dumps(report, indent=2))
    return 0 if report["blind_target_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
