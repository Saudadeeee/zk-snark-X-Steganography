"""
blind_contract_operating_point.py - Compare blind-core operating contract vs locked SEC1 contract.
"""

import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    OUTPUT_DIR,
    RESULTS_DIR,
    cache_load,
    cache_save,
    compute_quality_streaming,
    decode_luma_frames,
    save_fig,
    select_best_sec1_operating_asset,
    setup_style,
)
from benchmark.sec4_security import chi_square_t1_signs, _get_t1_signs, spa_estimate, rs_analysis
from src.blind_sync import derive_blind_positions_validated_pool_proxy
from src.embedder import embed
from src.exceptions import InsufficientCapacityError
from src.verifier import verify
from src.verifier_blind_keyed import verify_blind_keyed

CACHE_KEY = "blind_contract_operating_point"
SECRET_KEY = bytes(range(32))
CHAOS_KEY = b"sec1_benchmark_chaos_v1"
LOCKED_MESSAGE = b"ZK-bench-v1.0!"
BLIND_MESSAGE = b"Hello ZK-Stego"


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_CONTRACT_FAST", "0") == "1"


def _load_positions(seq_name: str) -> list[tuple[int, int, int]]:
    path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264.positions.json"
    return [tuple(int(v) for v in row) for row in json.loads(path.read_text(encoding="utf-8"))]


def _security_summary(stego_path: str, original_path: str) -> dict[str, float]:
    cover_signs = _get_t1_signs(Path(original_path))
    stego_signs = _get_t1_signs(Path(stego_path))
    _, chi_p = chi_square_t1_signs(stego_signs, cover_signs=cover_signs)

    max_frames = 60 if _fast_mode_enabled() else 180
    frames = decode_luma_frames(stego_path, max_frames=max_frames)
    flat = np.concatenate([f.flatten() for f in frames]) if len(frames) else np.array([], dtype=np.float32)
    spa = float(spa_estimate(frames)) if len(frames) else 0.0
    rs = float(rs_analysis(flat)["delta"]) if len(flat) else 0.0
    return {
        "chi_square_p": float(chi_p),
        "spa": spa,
        "rs_delta": rs,
    }


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] blind contract operating point")
        return cached

    seq_name, original_path = select_best_sec1_operating_asset(
        required_bits=1232,
        preferred_sequences=["deadline_q22_g1", "coastguard_q22_g1"],
    )
    if not seq_name or not original_path:
        raise RuntimeError("No SEC1 operating asset available")

    original_path = str(original_path)
    locked_stego = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264"
    if not locked_stego.exists():
        raise RuntimeError(f"Missing locked SEC1 stego artifact for {seq_name}")

    locked_positions = _load_positions(seq_name)

    # Locked contract
    locked_quality = compute_quality_streaming(original_path, str(locked_stego), max_frames=180)
    locked_verify = verify(
        stego_video_path=str(locked_stego),
        original_video_path=original_path,
        circuits_dir="circuits",
        secret_key=SECRET_KEY,
        message_length=len(LOCKED_MESSAGE),
        chaos_key=CHAOS_KEY,
        precomputed_positions=locked_positions,
        precomputed_payload_bits=len(locked_positions),
        use_analysis_cache=True,
    )
    locked_security = _security_summary(str(locked_stego), original_path)

    # Blind-core contract
    required_bits = (4 + len(BLIND_MESSAGE) + 129) * 8
    blind_positions, blind_metadata = derive_blind_positions_validated_pool_proxy(
        original_path,
        SECRET_KEY,
        required_bits=required_bits,
        use_analysis_cache=True,
    )
    blind_out = OUTPUT_DIR / f"_blind_contract_{seq_name}.h264"
    try:
        blind_embed = embed(
            video_path=original_path,
            message=BLIND_MESSAGE,
            output_path=str(blind_out),
            circuits_dir="circuits",
            secret_key=SECRET_KEY,
            precomputed_positions=blind_positions,
            trust_precomputed_positions=True,
            use_analysis_cache=True,
        )
        q_frames = 60 if _fast_mode_enabled() else 180
        blind_quality = compute_quality_streaming(original_path, str(blind_out), max_frames=q_frames)
        if _fast_mode_enabled():
            blind_verify_valid = None
            blind_verify_message_match = None
            blind_verify_metadata = None
        else:
            blind_verify, blind_verify_metadata = verify_blind_keyed(
                str(blind_out),
                "circuits",
                SECRET_KEY,
                message_length=len(BLIND_MESSAGE),
                use_analysis_cache=True,
            )
            blind_verify_valid = bool(blind_verify.valid)
            blind_verify_message_match = blind_verify.message == BLIND_MESSAGE
        blind_security = _security_summary(str(blind_out), original_path)
        data = {
            "sequence": seq_name,
            "locked_contract": {
                "message_length": len(LOCKED_MESSAGE),
                "bits": len(locked_positions),
                "quality": locked_quality,
                "verify_valid": bool(locked_verify.valid),
                "verify_message_match": locked_verify.message == LOCKED_MESSAGE,
                "security": locked_security,
            },
            "blind_contract": {
                "message_length": len(BLIND_MESSAGE),
                "bits": blind_embed.bits_embedded,
                "quality": blind_quality,
                "verify_valid": blind_verify_valid,
                "verify_message_match": blind_verify_message_match,
                "security": blind_security,
                "blind_metadata": blind_metadata.__dict__,
                "verify_metadata": (blind_verify_metadata.__dict__ if blind_verify_metadata is not None else None),
            },
        }
    except InsufficientCapacityError as exc:
        data = {
            "sequence": seq_name,
            "locked_contract": {
                "message_length": len(LOCKED_MESSAGE),
                "bits": len(locked_positions),
                "quality": locked_quality,
                "verify_valid": bool(locked_verify.valid),
                "verify_message_match": locked_verify.message == LOCKED_MESSAGE,
                "security": locked_security,
            },
            "blind_contract": {
                "message_length": len(BLIND_MESSAGE),
                "bits": 0,
                "verify_valid": False,
                "verify_message_match": False,
                "error": str(exc),
                "failure_stage": exc.context.get("stage"),
                "blind_metadata": blind_metadata.__dict__,
            },
        }
    finally:
        for path in (
            blind_out,
            Path(f"{blind_out}.positions.json"),
            Path(f"{blind_out}.meta.json"),
            Path(f"{blind_out}.manifest.json"),
        ):
            if path.exists():
                path.unlink()

    cache_save(CACHE_KEY, data)
    return data


def plot_comparison(data: dict) -> None:
    setup_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["locked_contract", "blind_contract"]
    psnr_vals = [
        float(data["locked_contract"]["quality"]["psnr_full_video"]),
        float(data["blind_contract"].get("quality", {}).get("psnr_full_video", 0.0)) if data["blind_contract"].get("quality") else 0.0,
    ]
    bits_vals = [
        int(data["locked_contract"]["bits"]),
        int(data["blind_contract"]["bits"]),
    ]
    x = np.arange(len(labels))
    bars = ax.bar(x, psnr_vals, color=[ "#1565C0", "#E65100" ], width=0.55, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Full-video PSNR (dB)")
    ax.set_title("Blind-core contract vs locked operating contract")
    for bar, psnr_val, bit_val in zip(bars, psnr_vals, bits_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                f"{psnr_val:.2f} dB\n{bit_val} bits", ha="center", va="bottom", fontsize=9)
    save_fig(fig, "blind_contract_operating_point")


def run(force: bool = False) -> dict:
    print("\n=== Blind Contract Operating Point ===")
    data = collect_data(force=force)
    plot_comparison(data)
    print(
        f"  [{data['sequence']}] locked_valid={data['locked_contract']['verify_valid']} "
        f"blind_valid={data['blind_contract'].get('verify_valid')}"
    )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
