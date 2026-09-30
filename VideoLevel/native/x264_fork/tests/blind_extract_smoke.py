"""Blindly rederive the direct-CAVLC smoke carrier positions from H.264."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.blind_sync import parse_blind_payload_header, unpack_blind_payload
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser


def extract_blind_payload(video_path: Path) -> bytes:
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
    idr = next(nal for nal in nal_units if int(nal.nal_unit_type) == 5)
    parsed = TraceableCAVLCParser().extract_with_offsets(idr, sps, pps)
    if parsed.get("parse_trusted") is not True or parsed.get("parse_integrity_issues"):
        raise ValueError(f"CAVLC parse is not trusted: {parsed.get('parse_integrity_issues')}")

    blocks = parsed["blocks"]
    metadata = parsed["mb_metadata"]
    bits: list[int] = []
    # The fork embeds in the first eligible luma block in ascending I4x4
    # block order; trellis makes the encoder visit that same complete order.
    for mb_index in sorted(metadata):
        if metadata[mb_index].get("mb_type") != 0:
            continue
        found_carrier = False
        for block_index in range(16):
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

    def bits_to_bytes(count: int) -> bytes:
        if len(bits) < count * 8:
            raise ValueError(f"video has {len(bits)} readable bits; need {count * 8}")
        payload = bytearray(count)
        for bit_index, bit in enumerate(bits[:count * 8]):
            payload[bit_index // 8] |= bit << (7 - (bit_index % 8))
        return bytes(payload)

    header = bits_to_bytes(14)
    payload_size = parse_blind_payload_header(header)
    envelope = bits_to_bytes(14 + payload_size)
    return unpack_blind_payload(envelope)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("expected_payload_hex", help="fixture assertion; length is read from video")
    args = parser.parse_args()
    expected = bytes.fromhex(args.expected_payload_hex)
    actual = extract_blind_payload(args.video)
    if actual != expected:
        raise SystemExit(f"blind extraction mismatch: got {actual.hex()}, expected {expected.hex()}")
    print(f"PASS blind_extract_bytes={len(actual)} payload={actual.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
