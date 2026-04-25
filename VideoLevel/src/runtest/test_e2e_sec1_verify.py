"""
E2E verify test for sec1 stego files (v5: chaos_v5_ffmpeg_validated).

Stego files created with:
  1. chaos.shuffle_positions(safe_positions) via Logistic Map (CHAOS_KEY)
  2. dedup by (mb_idx, block_idx) for max_mods_per_block=1 compatibility
  3. FFmpeg per-position validation with per-IDR cap (SEC1_MAX_FLIPS_PER_IDR=5)
  4. embed exactly N validated positions

This test mirrors the embedding logic exactly so extraction is deterministic.
If a <stego>.positions.json file exists alongside the stego, validated positions
are loaded directly (skipping the expensive FFmpeg re-validation step).

Usage:
  $env:BENCHMARK_TRUSTED_IDR_PICKLE_CACHE='1'
  python src/runtest/test_e2e_sec1_verify.py
"""
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ.setdefault("BENCHMARK_TRUSTED_IDR_PICKLE_CACHE", "1")

from src.core.pipeline import extract_bits_direct
from src.core.stego import CAVLCSafetyFilter
from src.core.chaos import ChaosTransformer
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.zk_proof import ZKSnarkBridge, unpack, blob_bit_length
from benchmark._common import load_or_extract_idr_blocks

ROOT = Path(__file__).resolve().parent.parent.parent
CIRCUITS_DIR = str(ROOT / "circuits")
DATA_DIR = ROOT / "data"
OUTPUT_DIR = DATA_DIR / "output"
ENCODED_DIR = DATA_DIR / "encoded"

SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec1_benchmark_chaos_v1"
REAL_PROOF_MESSAGE = b"ZK-bench-v1.0!"
CIF_MB_COUNT = 396
SEC1_MAX_FLIPS_PER_IDR = 5

SEQUENCES = {
    "foreman_q22_g1": (
        OUTPUT_DIR / "sec1_stego_foreman_q22_g1.h264",
        ENCODED_DIR / "foreman_cif_q22_g1.h264",
    ),
    "coastguard_q22_g1": (
        OUTPUT_DIR / "sec1_stego_coastguard_q22_g1.h264",
        ENCODED_DIR / "coastguard_cif_q22_g1.h264",
    ),
}


def _get_validated_positions(original_path: Path, rec: BitstreamReconstructor,
                              coefficients, frame_verified_data, nC_map,
                              nal_length_map, t1_override_map,
                              extract_bit_count: int) -> list:
    """Reproduce embedding position selection: shuffle → dedup → FFmpeg validate."""
    safety = CAVLCSafetyFilter()
    safe_positions = safety.get_safe_positions(
        coefficients,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
    )

    chaos = ChaosTransformer(CHAOS_KEY)
    shuffled = chaos.shuffle_positions(safe_positions)

    # Deduplicate by (mb_idx, block_idx)
    seen_blk: set = set()
    deduped: list = []
    for p in shuffled:
        bk = (p[0], p[1])
        if bk not in seen_blk:
            seen_blk.add(bk)
            deduped.append(p)

    # FFmpeg per-position validation (same as embedding)
    validator, cleanup = rec.make_ffmpeg_position_validator(
        str(original_path), coefficients, frame_verified_data
    )
    validated: list = []
    idr_flip: dict[int, int] = {}
    try:
        for p in deduped:
            if len(validated) >= extract_bit_count:
                break
            fi = p[0] // CIF_MB_COUNT
            if idr_flip.get(fi, 0) >= SEC1_MAX_FLIPS_PER_IDR:
                continue
            if validator(p[0], p[1], p[2]):
                validated.append(p)
                idr_flip[fi] = idr_flip.get(fi, 0) + 1
    finally:
        cleanup()

    return validated


def verify_v5(seq_name: str, stego_path: Path, original_path: Path) -> bool:
    """Verify v5 stego: chaos shuffle + dedup + FFmpeg validation + Arnold unscramble."""
    print(f"\n[{seq_name}] Parsing original video (with pickle cache)...")
    rec = BitstreamReconstructor()
    coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map = \
        load_or_extract_idr_blocks(original_path, rec)

    print(f"  coefficients: {len(coefficients)} blocks")

    original_bit_count = blob_bit_length(b"\x00" * len(REAL_PROOF_MESSAGE))
    padded_bits = ChaosTransformer.padded_bit_count(original_bit_count)
    extract_bit_count = math.ceil(padded_bits / 8) * 8
    print(f"  extract_bit_count={extract_bit_count} (original={original_bit_count}, padded={padded_bits})")

    pos_json = stego_path.parent / f"{stego_path.name}.positions.json"
    if pos_json.exists():
        print(f"  Loading validated positions from {pos_json.name}...")
        with open(pos_json) as _f:
            validated = [tuple(p) for p in json.load(_f)]
        print(f"  validated positions: {len(validated)} (from JSON cache)")
    else:
        print(f"  Running FFmpeg validation to find {extract_bit_count} valid positions...")
        validated = _get_validated_positions(
            original_path, rec, coefficients, frame_verified_data,
            nC_map, nal_length_map, t1_override_map, extract_bit_count
        )
        print(f"  validated positions: {len(validated)}")

    if len(validated) < extract_bit_count:
        print(f"  FAIL: only {len(validated)} validated positions, need {extract_bit_count}")
        return False

    extracted_blob = extract_bits_direct(
        str(stego_path),
        validated,
        frame_verified_data,
        nC_map,
        extract_bit_count,
        max_modifications_per_block=1,
    )
    print(f"  extracted {len(extracted_blob)*8} bits")

    chaos = ChaosTransformer(CHAOS_KEY)
    unscrambled = chaos.unscramble(extracted_blob, original_bit_count)
    print(f"  unscrambled to {len(unscrambled)*8} bits")

    try:
        message, proof_bytes = unpack(unscrambled)
    except ValueError as e:
        print(f"  FAIL unpack: {e}")
        return False

    message_match = (message == REAL_PROOF_MESSAGE)
    print(f"  message: {message!r}  match={message_match}")

    bridge = ZKSnarkBridge(CIRCUITS_DIR)
    proof_dict = bridge.bytes_to_proof(proof_bytes)
    public_signals = bridge._build_public_signals(message, SECRET_KEY)
    is_valid = bridge.verify(proof_dict, public_signals)
    print(f"  ZK valid: {is_valid}")

    return is_valid and message_match


if __name__ == "__main__":
    all_pass = True
    for seq_name, (stego_path, original_path) in SEQUENCES.items():
        if not stego_path.exists():
            print(f"[{seq_name}] SKIP: {stego_path}")
            continue
        if not original_path.exists():
            print(f"[{seq_name}] SKIP: {original_path}")
            continue
        ok = verify_v5(seq_name, stego_path, original_path)
        print(f"[{seq_name}] {'PASS' if ok else 'FAIL'}")
        all_pass = all_pass and ok

    print(f"\n{'ALL PASS' if all_pass else 'SOME FAILED'}")
    sys.exit(0 if all_pass else 1)
