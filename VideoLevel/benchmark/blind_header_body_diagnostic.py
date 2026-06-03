"""
blind_header_body_diagnostic.py - Blind two-tier header/body diagnostic.

Tests a blind contract with:
  - a repeated blind-derived header subset
  - a broader blind-derived body subset

Metrics:
  - header decode success rate
  - full payload decode success rate
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, cache_load, cache_save, load_or_build_benchmark_analysis
from src.blind_sync import derive_blind_body_positions, derive_blind_header_positions
from src.core.pipeline import extract_bits_direct
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.stego import PayloadEmbedder
from src.zk_proof import unpack
from src.zk_proof import PROOF_SIZE_BYTES

CACHE_KEY = "blind_header_body_diagnostic"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
HEADER_REDUNDANCY_LEVELS = [1, 4, 8]


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


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_HEADER_FAST", "0") == "1"


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind header/body diagnostic")
        return cached

    proof_bytes = bytes([i % 256 for i in range(PROOF_SIZE_BYTES)])
    original_blob = len(MESSAGE).to_bytes(4, "big") + MESSAGE + proof_bytes
    original_bits = _bytes_to_bits(original_blob)
    body_bits = original_bits[HEADER_BITS:]
    required_bits = len(original_bits)
    assets = ["coastguard_q22_g1", "deadline_q22_g1"] if not _fast_mode_enabled() else ["coastguard_q22_g1"]
    data = {"message_length": len(MESSAGE), "required_bits": required_bits, "assets": {}}

    for seq_name in assets:
        video_path = str(SEQUENCES[seq_name])
        if not Path(video_path).exists():
            continue
        coeffs, fvd, nC_map, nal_len, t1_over, _safe = load_or_build_benchmark_analysis(video_path, force=force)
        rows = []
        for redundancy in HEADER_REDUNDANCY_LEVELS:
            header_positions, _ = derive_blind_header_positions(
                video_path,
                SECRET_KEY,
                header_bits=HEADER_BITS * redundancy,
                use_analysis_cache=True,
            )
            body_positions, _ = derive_blind_body_positions(
                video_path,
                SECRET_KEY,
                body_bits=len(body_bits),
                header_positions=header_positions,
                use_analysis_cache=True,
            )
            positions = header_positions + body_positions
            header_repeated = []
            for bit in original_bits[:HEADER_BITS]:
                header_repeated.extend([bit] * redundancy)
            payload_bits = header_repeated + body_bits
            payload_bytes = _bits_to_bytes(payload_bits)
            out_path = Path("data/output") / f"_blind_header_{seq_name}_r{redundancy}.h264"
            row = {
                "redundancy": redundancy,
                "header_positions": len(header_positions),
                "body_positions": len(body_positions),
                "positions_total": len(positions),
                "header_success": False,
                "full_payload_success": False,
            }
            try:
                embedder = PayloadEmbedder(max_modifications_per_block=1)
                modified, bits_embedded = embedder.embed_payload(
                    coeffs,
                    payload_bytes,
                    nC_map=nC_map,
                    nal_length_map=nal_len,
                    t1_override_map=t1_over,
                    frame_verified_data=fvd,
                    pre_validated_positions=positions,
                )
                rec = BitstreamReconstructor()
                rec.reconstruct_video(
                    video_path,
                    modified,
                    str(out_path),
                    max_slices=None,
                    frame_verified_data=fvd,
                )
                _, stego_fvd, stego_nC, _, _, _ = load_or_build_benchmark_analysis(str(out_path), force=True)
                derived_header, _ = derive_blind_header_positions(
                    str(out_path),
                    SECRET_KEY,
                    header_bits=HEADER_BITS * redundancy,
                    use_analysis_cache=True,
                )
                derived_body, _ = derive_blind_body_positions(
                    str(out_path),
                    SECRET_KEY,
                    body_bits=len(body_bits),
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
                extracted_bits = _bytes_to_bits(blob)[:len(payload_bits)]
                header_voted = _majority_vote(extracted_bits[: HEADER_BITS * redundancy], redundancy)
                header_len = int.from_bytes(_bits_to_bytes(header_voted[:HEADER_BITS])[:4], "big")
                row["header_success"] = (header_len == len(MESSAGE))
                reconstructed_blob = _bits_to_bytes(header_voted[:HEADER_BITS] + extracted_bits[HEADER_BITS * redundancy :])
                try:
                    msg, _proof = unpack(reconstructed_blob)
                    row["full_payload_success"] = (msg == MESSAGE)
                except Exception:
                    row["full_payload_success"] = False
                row["bits_embedded"] = bits_embedded
                row["decoded_length"] = header_len
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
        data["assets"][seq_name] = {"rows": rows}

    if data["assets"]:
        all_rows = [row for asset in data["assets"].values() for row in asset["rows"]]
        data["header_success_rate"] = sum(1 for r in all_rows if r["header_success"]) / len(all_rows)
        data["full_payload_success_rate"] = sum(1 for r in all_rows if r["full_payload_success"]) / len(all_rows)
    else:
        data["header_success_rate"] = 0.0
        data["full_payload_success_rate"] = 0.0

    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Header/Body Diagnostic ===")
    data = collect_data(force=force)
    print(
        f"  header_success_rate={data['header_success_rate']:.3f} "
        f"full_payload_success_rate={data['full_payload_success_rate']:.3f}"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
