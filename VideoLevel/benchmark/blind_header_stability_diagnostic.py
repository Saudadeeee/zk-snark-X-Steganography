"""
blind_header_stability_diagnostic.py - Measure per-position readout stability for blind header candidates.

This benchmark probes a subset of blind-derived candidate positions and tests
whether a single embedded bit can be read back reliably after reconstruction.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, cache_load, cache_save, load_or_build_benchmark_analysis
from benchmark.locked_operating_contract import load_best_locked_operating_contract
from src.blind_sync import derive_blind_positions_validated_pool_proxy
from src.core.analysis_cache import load_or_build_video_analysis
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.pipeline import extract_bits_direct
from src.core.stego import PayloadEmbedder

CACHE_KEY = "blind_header_stability_diagnostic"
SECRET_KEY = bytes(range(32))
PROBE_LIMIT_FAST = 32
PROBE_LIMIT_FULL = 96


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_HEADER_FAST", "0") == "1"


def _probe_position(
    video_path: str,
    position: tuple[int, int, int],
    embed_bit: int,
    coefficients,
    frame_verified_data,
    nC_map,
    nal_length_map,
    t1_override_map,
) -> bool:
    payload = bytes([0x80 if embed_bit else 0x00])
    out_path = Path("data/output") / "_blind_header_probe.h264"
    try:
        embedder = PayloadEmbedder(max_modifications_per_block=1)
        modified, bits_embedded = embedder.embed_payload(
            coefficients,
            payload,
            nC_map=nC_map,
            nal_length_map=nal_length_map,
            t1_override_map=t1_override_map,
            frame_verified_data=frame_verified_data,
            pre_validated_positions=[position],
        )
        if bits_embedded < 1:
            return False
        rec = BitstreamReconstructor()
        rec.reconstruct_video(
            video_path,
            modified,
            str(out_path),
            max_slices=None,
            frame_verified_data=frame_verified_data,
        )
        _, stego_fvd, stego_nC, _, _, _ = load_or_build_video_analysis(str(out_path), use_cache=False)
        blob = extract_bits_direct(
            str(out_path),
            [position],
            stego_fvd,
            stego_nC,
            8,
            max_modifications_per_block=1,
        )
        bit_out = (blob[0] >> 7) & 1 if blob else None
        return bit_out == embed_bit
    finally:
        for path in (
            out_path,
            Path(f"{out_path}.positions.json"),
            Path(f"{out_path}.meta.json"),
            Path(f"{out_path}.manifest.json"),
        ):
            if path.exists():
                path.unlink()


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind header stability diagnostic")
        return cached

    contract = load_best_locked_operating_contract(required_bits=1232)
    if contract is None:
        raise RuntimeError("No locked operating contract available")

    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(contract.video_path, force=force)

    blind_positions, metadata = derive_blind_positions_validated_pool_proxy(
        contract.video_path,
        SECRET_KEY,
        required_bits=128,
        use_analysis_cache=True,
    )

    probe_limit = PROBE_LIMIT_FAST if _fast_mode_enabled() else PROBE_LIMIT_FULL
    candidates = blind_positions[:probe_limit]

    rows = []
    for pos in candidates:
        ok0 = _probe_position(
            contract.video_path,
            pos,
            0,
            coefficients,
            frame_verified_data,
            nC_map,
            nal_length_map,
            t1_override_map,
        )
        ok1 = _probe_position(
            contract.video_path,
            pos,
            1,
            coefficients,
            frame_verified_data,
            nC_map,
            nal_length_map,
            t1_override_map,
        )
        score = int(ok0) + int(ok1)
        rows.append(
            {
                "position": [int(pos[0]), int(pos[1]), int(pos[2])],
                "bit0_ok": bool(ok0),
                "bit1_ok": bool(ok1),
                "score": score,
            }
        )

    rows.sort(key=lambda row: row["score"], reverse=True)
    perfect = [row for row in rows if row["score"] == 2]

    data = {
        "sequence": contract.sequence_name,
        "video_path": contract.video_path,
        "probe_limit": probe_limit,
        "perfect_readout_count": len(perfect),
        "perfect_readout_ratio": len(perfect) / max(1, len(rows)),
        "metadata": metadata.__dict__,
        "rows": rows,
    }
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Header Stability Diagnostic ===")
    data = collect_data(force=force)
    print(
        f"  [{data['sequence']}] perfect_readout={data['perfect_readout_count']}/{data['probe_limit']} "
        f"({data['perfect_readout_ratio']:.3f})"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
