"""
blind_body_hamming_diagnostic.py - Probe a simple ECC layer for blind body decoding.

Uses:
  - a repeated blind header (stable)
  - a Hamming(7,4)-coded body prefix

Goal:
  measure whether a lightweight ECC is enough to push blind-core body decoding
  from "almost correct" to "correct enough for prefix reconstruction".
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, cache_load, cache_save, load_or_build_benchmark_analysis
from src.blind_sync import derive_blind_body_positions, derive_blind_header_positions
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.pipeline import extract_bits_direct
from src.core.stego import PayloadEmbedder

CACHE_KEY = "blind_body_hamming_diagnostic"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
HEADER_REDUNDANCY = 4
BODY_BITS = 128


def _bits_to_bytes(bits: list[int]) -> bytes:
    padded = list(bits)
    while len(padded) % 8:
        padded.append(0)
    out = bytearray()
    for i in range(0, len(padded), 8):
        byte = 0
        for bit in padded[i:i + 8]:
            byte = (byte << 1) | int(bit)
        out.append(byte)
    return bytes(out)


def _bytes_to_bits(data: bytes) -> list[int]:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _majority_vote(bits: list[int], redundancy: int) -> list[int]:
    out = []
    for i in range(0, len(bits), redundancy):
        chunk = bits[i:i + redundancy]
        out.append(1 if sum(chunk) > len(chunk) / 2 else 0)
    return out


def _hamming74_encode(bits: list[int]) -> list[int]:
    out = []
    for i in range(0, len(bits), 4):
        d = bits[i:i + 4]
        while len(d) < 4:
            d.append(0)
        d1, d2, d3, d4 = d
        p1 = d1 ^ d2 ^ d4
        p2 = d1 ^ d3 ^ d4
        p3 = d2 ^ d3 ^ d4
        out.extend([p1, p2, d1, p3, d2, d3, d4])
    return out


def _hamming74_decode(bits: list[int]) -> list[int]:
    out = []
    for i in range(0, len(bits), 7):
        w = bits[i:i + 7]
        if len(w) < 7:
            break
        b = w[:]
        s1 = b[0] ^ b[2] ^ b[4] ^ b[6]
        s2 = b[1] ^ b[2] ^ b[5] ^ b[6]
        s3 = b[3] ^ b[4] ^ b[5] ^ b[6]
        syndrome = s1 | (s2 << 1) | (s3 << 2)
        if syndrome != 0 and 1 <= syndrome <= 7:
            b[syndrome - 1] ^= 1
        out.extend([b[2], b[4], b[5], b[6]])
    return out


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind body hamming diagnostic")
        return cached

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])

    synthetic_proof_prefix = bytes([i % 256 for i in range(32)])
    blob = len(MESSAGE).to_bytes(4, "big") + MESSAGE + synthetic_proof_prefix
    blob_bits = _bytes_to_bits(blob)
    header_bits = blob_bits[:HEADER_BITS]
    body_bits = blob_bits[HEADER_BITS : HEADER_BITS + BODY_BITS]
    encoded_body = _hamming74_encode(list(body_bits))

    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    repeated_header = []
    for bit in header_bits:
        repeated_header.extend([bit] * HEADER_REDUNDANCY)
    header_positions, _ = derive_blind_header_positions(
        video_path,
        SECRET_KEY,
        header_bits=len(repeated_header),
        use_analysis_cache=True,
    )
    body_positions, _ = derive_blind_body_positions(
        video_path,
        SECRET_KEY,
        body_bits=len(encoded_body),
        header_positions=header_positions,
        use_analysis_cache=True,
    )
    positions = header_positions + body_positions
    payload_bits = repeated_header + encoded_body
    payload = _bits_to_bytes(payload_bits)
    out_path = Path("data/output") / "_blind_body_hamming.h264"
    try:
        embedder = PayloadEmbedder(max_modifications_per_block=1)
        modified, bits_embedded = embedder.embed_payload(
            coefficients,
            payload,
            nC_map=nC_map,
            nal_length_map=nal_length_map,
            t1_override_map=t1_override_map,
            frame_verified_data=frame_verified_data,
            pre_validated_positions=positions,
        )
        rec = BitstreamReconstructor()
        rec.reconstruct_video(
            video_path,
            modified,
            str(out_path),
            max_slices=None,
            frame_verified_data=frame_verified_data,
        )
        _, stego_fvd, stego_nC, _, _, _ = load_or_build_benchmark_analysis(str(out_path), force=True)
        derived_header, _ = derive_blind_header_positions(
            str(out_path),
            SECRET_KEY,
            header_bits=len(repeated_header),
            use_analysis_cache=True,
        )
        derived_body, _ = derive_blind_body_positions(
            str(out_path),
            SECRET_KEY,
            body_bits=len(encoded_body),
            header_positions=derived_header,
            use_analysis_cache=True,
        )
        derived_positions = derived_header + derived_body
        blob_out = extract_bits_direct(
            str(out_path),
            derived_positions,
            stego_fvd,
            stego_nC,
            len(payload_bits),
            max_modifications_per_block=1,
        )
        out_bits = _bytes_to_bits(blob_out)[: len(payload_bits)]
        header_voted = _majority_vote(out_bits[: len(repeated_header)], HEADER_REDUNDANCY)
        body_decoded = _hamming74_decode(out_bits[len(repeated_header): len(repeated_header) + len(encoded_body)])
        header_ok = int.from_bytes(_bits_to_bytes(header_voted)[:4], "big") == len(MESSAGE)
        body_matches = sum(1 for a, b in zip(body_bits, body_decoded[: len(body_bits)]) if a == b)
        data = {
            "sequence": seq_name,
            "bits_embedded": bits_embedded,
            "header_success": header_ok,
            "body_bits_probed": len(body_bits),
            "body_bits_matched": body_matches,
            "body_match_ratio": body_matches / max(1, len(body_bits)),
            "full_prefix_success": header_ok and body_matches == len(body_bits),
        }
    finally:
        for path in (
            out_path,
            Path(f"{out_path}.positions.json"),
            Path(f"{out_path}.meta.json"),
            Path(f"{out_path}.manifest.json"),
        ):
            if path.exists():
                path.unlink()

    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Body Hamming Diagnostic ===")
    data = collect_data(force=force)
    print(
        f"  header={data['header_success']} "
        f"body_match={data['body_bits_matched']}/{data['body_bits_probed']} "
        f"({data['body_match_ratio']:.3f}) full_prefix={data['full_prefix_success']}"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
