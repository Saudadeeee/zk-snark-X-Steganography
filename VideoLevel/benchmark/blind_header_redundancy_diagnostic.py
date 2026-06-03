"""
blind_header_redundancy_diagnostic.py - Evaluate repeated blind-header encoding.

This diagnostic does not try to decode the full payload. It focuses only on the
header bottleneck by repeating each header bit multiple times and applying
majority vote on extraction.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, cache_load, cache_save, load_or_build_benchmark_analysis
from benchmark.locked_operating_contract import load_best_locked_operating_contract
from src.blind_sync import derive_blind_positions_validated_pool_proxy
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.pipeline import extract_bits_direct
from src.core.stego import PayloadEmbedder

CACHE_KEY = "blind_header_redundancy_diagnostic"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
REDUNDANCY_LEVELS = [1, 2, 4, 8]


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


def _majority_vote(bits: list[int], redundancy: int) -> list[int]:
    voted = []
    for i in range(0, len(bits), redundancy):
        chunk = bits[i:i + redundancy]
        ones = sum(chunk)
        voted.append(1 if ones > (len(chunk) / 2) else 0)
    return voted


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind header redundancy diagnostic")
        return cached

    contract = load_best_locked_operating_contract(required_bits=1232)
    if contract is None:
        raise RuntimeError("No locked operating contract available")

    header_bits = [(len(MESSAGE).to_bytes(4, "big")[i // 8] >> (7 - (i % 8))) & 1 for i in range(HEADER_BITS)]
    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(contract.video_path, force=force)

    rows = []
    for redundancy in REDUNDANCY_LEVELS:
        repeated_bits = []
        for bit in header_bits:
            repeated_bits.extend([bit] * redundancy)
        payload = _bits_to_bytes(repeated_bits)
        required_bits = len(repeated_bits)
        blind_positions, _ = derive_blind_positions_validated_pool_proxy(
            contract.video_path,
            SECRET_KEY,
            required_bits=required_bits,
            use_analysis_cache=True,
        )
        out_path = Path("data/output") / f"_blind_header_redundancy_r{redundancy}.h264"
        try:
            embedder = PayloadEmbedder(max_modifications_per_block=1)
            modified, bits_embedded = embedder.embed_payload(
                coefficients,
                payload,
                nC_map=nC_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map,
                frame_verified_data=frame_verified_data,
                pre_validated_positions=blind_positions,
            )
            rec = BitstreamReconstructor()
            rec.reconstruct_video(
                contract.video_path,
                modified,
                str(out_path),
                max_slices=None,
                frame_verified_data=frame_verified_data,
            )
            _, stego_fvd, stego_nC, _, _, _ = load_or_build_benchmark_analysis(str(out_path), force=True)
            blob = extract_bits_direct(
                str(out_path),
                blind_positions,
                stego_fvd,
                stego_nC,
                required_bits,
                max_modifications_per_block=1,
            )
            extracted_bits = []
            for bit_idx in range(required_bits):
                byte = blob[bit_idx // 8]
                extracted_bits.append((byte >> (7 - (bit_idx % 8))) & 1)
            voted = _majority_vote(extracted_bits[:required_bits], redundancy)
            decoded_length = int.from_bytes(_bits_to_bytes(voted[:HEADER_BITS])[:4], "big")
            rows.append(
                {
                    "redundancy": redundancy,
                    "required_bits": required_bits,
                    "bits_embedded": bits_embedded,
                    "decoded_length": decoded_length,
                    "header_success": decoded_length == len(MESSAGE),
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
        "sequence": contract.sequence_name,
        "message_length": len(MESSAGE),
        "rows": rows,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Header Redundancy Diagnostic ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  r={row['redundancy']} decoded_length={row['decoded_length']} "
            f"success={row['header_success']}"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
