"""
blind_real_proof_header_diagnostic.py - Isolate header robustness on the real-proof branch.

This benchmark focuses only on the 4-byte message-length header while keeping
the real-proof branch assumptions:
- same all-intra asset
- same blind header derivation
- no proof-prefix or message body mixed into the payload

The goal is to understand which header coding levels are stable before they are
recombined with the real-proof body branch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, cache_load, cache_save, load_or_build_benchmark_analysis
from src.blind_sync import derive_blind_header_positions
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.pipeline import extract_bits_direct
from src.core.stego import PayloadEmbedder

CACHE_KEY = "blind_real_proof_header_diagnostic"
SECRET_KEY = bytes(range(32))
MESSAGE = b"ZK-bench-v1.0!"
HEADER_BITS = 32
REDUNDANCY_LEVELS = [4, 8, 12]


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
    bits: list[int] = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _majority_vote(bits: list[int], redundancy: int) -> list[int]:
    out: list[int] = []
    for i in range(0, len(bits), redundancy):
        chunk = bits[i:i + redundancy]
        out.append(1 if sum(chunk) > len(chunk) / 2 else 0)
    return out


def _repeat_bits(bits: list[int], redundancy: int) -> list[int]:
    repeated: list[int] = []
    for bit in bits:
        repeated.extend([bit] * redundancy)
    return repeated


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        rows = cached.get("rows") if isinstance(cached, dict) else None
        if isinstance(rows, list) and all(isinstance(row, dict) and "redundancy" in row for row in rows):
            print("  [cache hit] blind real proof header diagnostic")
            return cached
        print("  [cache stale] blind real proof header diagnostic")

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])
    header_bits = _bytes_to_bits(len(MESSAGE).to_bytes(4, "big"))

    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    rows = []
    for redundancy in REDUNDANCY_LEVELS:
        repeated_header_bits = _repeat_bits(header_bits, redundancy)
        header_positions, _ = derive_blind_header_positions(
            video_path,
            SECRET_KEY,
            header_bits=len(repeated_header_bits),
            use_analysis_cache=True,
        )
        payload = _bits_to_bytes(repeated_header_bits)
        out_path = Path("data/output") / f"_blind_real_header_r{redundancy}.h264"
        row = {
            "redundancy": redundancy,
            "required_bits": len(repeated_header_bits),
            "header_success": False,
            "decoded_length": None,
            "length_bit_errors": None,
        }
        try:
            embedder = PayloadEmbedder(max_modifications_per_block=1)
            modified, bits_embedded = embedder.embed_payload(
                coefficients,
                payload,
                nC_map=nC_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map,
                frame_verified_data=frame_verified_data,
                pre_validated_positions=header_positions,
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
                header_bits=len(repeated_header_bits),
                use_analysis_cache=True,
            )
            blob = extract_bits_direct(
                str(out_path),
                derived_header,
                stego_fvd,
                stego_nC,
                len(repeated_header_bits),
                max_modifications_per_block=1,
            )
            extracted_bits = _bytes_to_bits(blob)[: len(repeated_header_bits)]
            header_voted = _majority_vote(extracted_bits, redundancy)[:HEADER_BITS]
            decoded_length = int.from_bytes(_bits_to_bytes(header_voted)[:4], "big")
            expected_bits = header_bits[:HEADER_BITS]
            bit_errors = sum(1 for a, b in zip(expected_bits, header_voted) if a != b)
            row.update(
                {
                    "bits_embedded": bits_embedded,
                    "decoded_length": decoded_length,
                    "header_success": decoded_length == len(MESSAGE),
                    "length_bit_errors": bit_errors,
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
        rows.append(row)

    data = {"sequence": seq_name, "rows": rows}
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Real Proof Header Diagnostic ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  r={row['redundancy']} decoded_length={row['decoded_length']} "
            f"header={row['header_success']} length_bit_errors={row['length_bit_errors']}"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
