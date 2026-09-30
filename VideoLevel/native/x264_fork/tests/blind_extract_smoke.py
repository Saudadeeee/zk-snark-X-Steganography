"""Blindly rederive the direct-CAVLC smoke carrier positions from H.264."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser
from src.blind_sync import parse_blind_payload_header, unpack_blind_payload


def extract_blind_payload(video_path: Path) -> bytes:
    return extract_payload(video_path, include_p_slices=False)


def carrier_block_order(nal_unit_type: int, mb_type: int | None) -> tuple[int, ...]:
    """Match x264's coefficient traversal for the macroblock carrier hook."""
    if not isinstance(mb_type, int):
        return ()
    if nal_unit_type == 5 and mb_type == 0:
        return tuple(range(16))
    if nal_unit_type == 1 and mb_type == 5:
        return tuple(range(16))
    if nal_unit_type == 1 and 0 <= mb_type <= 4:
        # x264 visits four 4x4 blocks per 8x8 group (0..3, then 4..7, ...),
        # and the parser keys blocks in that same H.264 scan-index order.
        return tuple(range(16))
    return ()


def extract_payload(video_path: Path, *, include_p_slices: bool) -> bytes:
    nal_units = H264BitstreamParser(str(video_path)).parse()
    reconstructor = BitstreamReconstructor()
    sps = next(
        reconstructor._parse_sps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 7
    )
    pps = next(
        reconstructor._parse_pps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 8
    )
    bits: list[int] = []
    payload_size: int | None = None

    def bits_to_bytes(count: int) -> bytes:
        if len(bits) < count * 8:
            raise ValueError(f"video has {len(bits)} readable bits; need {count * 8}")
        payload = bytearray(count)
        for bit_index, bit in enumerate(bits[:count * 8]):
            payload[bit_index // 8] |= bit << (7 - (bit_index % 8))
        return bytes(payload)

    # IDR-only mode remains the default. Inter-picture mode also examines
    # P-slice inter residuals in the exact block traversal used by x264.
    for nal in nal_units:
        nal_unit_type = int(nal.nal_unit_type)
        if nal_unit_type != 5 and not (include_p_slices and nal_unit_type == 1):
            continue
        parsed = TraceableCAVLCParser().extract_with_offsets(nal, sps, pps)
        if parsed.get("parse_trusted") is not True or parsed.get("parse_integrity_issues"):
            raise ValueError(
                f"CAVLC IDR parse is not trusted: {parsed.get('parse_integrity_issues')}"
            )

        blocks = parsed["blocks"]
        metadata = parsed["mb_metadata"]
        for mb_index in sorted(metadata):
            mb_type = metadata[mb_index].get("mb_type")
            block_order = carrier_block_order(nal_unit_type, mb_type)
            if not block_order:
                continue
            found_carrier = False
            for block_index in block_order:
                coefficients = blocks.get((mb_index, block_index))
                if coefficients is None:
                    continue
                for coefficient_index in range(15, 0, -1):
                    if abs(coefficients[coefficient_index]) >= 5:
                        bits.append(abs(coefficients[coefficient_index]) & 1)
                        found_carrier = True
                        break
                if found_carrier:
                    break

        if len(bits) >= 14 * 8:
            payload_size = parse_blind_payload_header(bits_to_bytes(14))
            if len(bits) >= (14 + payload_size) * 8:
                break

    header = bits_to_bytes(14)
    if payload_size is None:
        payload_size = parse_blind_payload_header(header)
    if len(bits) < (14 + payload_size) * 8:
        raise ValueError(
            f"video has {len(bits)} readable bits; need {(14 + payload_size) * 8}"
        )
    envelope = bits_to_bytes(14 + payload_size)
    return unpack_blind_payload(envelope)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("expected_payload_hex", help="fixture assertion; length is read from video")
    parser.add_argument("--include-p-slices", action="store_true")
    args = parser.parse_args()
    expected = bytes.fromhex(args.expected_payload_hex)
    actual = extract_payload(args.video, include_p_slices=args.include_p_slices)
    if actual != expected:
        raise SystemExit(f"blind extraction mismatch: got {actual.hex()}, expected {expected.hex()}")
    print(f"PASS blind_extract_bytes={len(actual)} payload={actual.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
