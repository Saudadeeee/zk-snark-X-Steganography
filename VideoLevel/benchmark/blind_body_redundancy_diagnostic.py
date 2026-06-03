"""
blind_body_redundancy_diagnostic.py - Probe blind body readout reliability.

Uses a working header redundancy scheme, then measures bit-match quality on a
short blind body segment under different redundancy levels.
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

CACHE_KEY = "blind_body_redundancy_diagnostic"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
HEADER_REDUNDANCY = 4
BODY_PROBE_BITS = 64
BODY_REDUNDANCY_LEVELS = [1, 2, 4]


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_HEADER_FAST", "0") == "1"


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


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind body redundancy diagnostic")
        return cached

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])
    required_bits = (4 + len(MESSAGE) + 129) * 8
    message_bits = _bytes_to_bits(MESSAGE)
    header_source_bits = [(len(MESSAGE).to_bytes(4, "big")[i // 8] >> (7 - (i % 8))) & 1 for i in range(HEADER_BITS)]
    body_source = message_bits[:BODY_PROBE_BITS]
    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    rows = []
    for body_redundancy in BODY_REDUNDANCY_LEVELS:
        header_positions, _ = derive_blind_header_positions(
            video_path,
            SECRET_KEY,
            header_bits=HEADER_BITS * HEADER_REDUNDANCY,
            use_analysis_cache=True,
        )
        repeated_body = []
        for bit in body_source:
            repeated_body.extend([bit] * body_redundancy)
        body_positions, _ = derive_blind_body_positions(
            video_path,
            SECRET_KEY,
            body_bits=len(repeated_body),
            header_positions=header_positions,
            use_analysis_cache=True,
        )
        positions = header_positions + body_positions
        payload_bits = []
        for bit in header_source_bits:
            payload_bits.extend([bit] * HEADER_REDUNDANCY)
        payload_bits.extend(repeated_body)
        payload = _bits_to_bytes(payload_bits)
        out_path = Path("data/output") / f"_blind_body_{seq_name}_r{body_redundancy}.h264"
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
                header_bits=HEADER_BITS * HEADER_REDUNDANCY,
                use_analysis_cache=True,
            )
            derived_body, _ = derive_blind_body_positions(
                str(out_path),
                SECRET_KEY,
                body_bits=len(repeated_body),
                header_positions=derived_header,
                use_analysis_cache=True,
            )
            derived_positions = derived_header + derived_body
            blob = extract_bits_direct(
                str(out_path),
                derived_positions,
                stego_fvd,
                stego_nC,
                len(payload_bits),
                max_modifications_per_block=1,
            )
            extracted_bits = _bytes_to_bits(blob)[: len(payload_bits)]
            body_offset = HEADER_BITS * HEADER_REDUNDANCY
            body_voted = _majority_vote(extracted_bits[body_offset : body_offset + len(repeated_body)], body_redundancy)
            matches = sum(1 for a, b in zip(body_source, body_voted[: len(body_source)]) if a == b)
            rows.append(
                {
                    "body_redundancy": body_redundancy,
                    "bits_embedded": bits_embedded,
                    "body_bits_probed": len(body_source),
                    "body_bits_matched": matches,
                    "body_match_ratio": matches / max(1, len(body_source)),
                }
            )
        finally:
            for path in (
                out_path,
                Path(f"{out_path}.positions.json"),
                Path(f"{out_path}.meta.json"),
                Path(f"{out_path}.manifest.json"),
            ):
                if path.exists():
                    path.unlink()

    data = {
        "sequence": seq_name,
        "rows": rows,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Body Redundancy Diagnostic ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  body_r={row['body_redundancy']} "
            f"match={row['body_bits_matched']}/{row['body_bits_probed']} "
            f"({row['body_match_ratio']:.3f})"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
