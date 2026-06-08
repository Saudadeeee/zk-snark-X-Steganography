"""
test_phase5_extract_verify.py - Phase 5: Public API round-trip and proof verification.

Tests:
  1. embed_api_sidecars_exist          - embed() produces a coherent stego artifact set
  2. zk_full_pipeline                  - real Groth16 proof path through embed()/verify()
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import (
    section,
    run_test,
    summarise,
    SKIP,
    get_video,
    get_output,
    get_circuits_dir,
    node_available,
)
from src.embedder import embed
from src.exceptions import InsufficientCapacityError
from src.verifier import verify
from benchmark._common import (
    load_sec1_positions,
    measure_patchable_usable_bits,
)
from benchmark.locked_operating_contract import (
    LOCKED_MESSAGE,
    LOCKED_SECRET_KEY,
    load_best_locked_operating_contract,
)


SECRET_KEY = LOCKED_SECRET_KEY
TEST_MSG = LOCKED_MESSAGE
CIRCUITS_DIR = get_circuits_dir()

# Prefer larger all-intra assets first because patchable capacity is the real constraint.
VIDEO_CANDIDATES = [
    get_video("deadline_cif_q22_g1.h264"),
    get_video("coastguard_cif_q22_g1_1000f.h264"),
    get_video("coastguard_cif_q22_g1.h264"),
    get_video("foreman_cif_q22_g1.h264"),
]
SCAN_JSON = Path(__file__).resolve().parent.parent.parent / "benchmark" / "results" / "patchable_capacity_scan.json"


def _first_embeddable_video(message: bytes) -> str | None:
    required_bits = (4 + len(message) + 129) * 8
    contract = load_best_locked_operating_contract(required_bits=required_bits)
    if contract is not None:
        return contract.video_path
    if SCAN_JSON.exists():
        try:
            cached = json.loads(SCAN_JSON.read_text(encoding="utf-8"))
            scan_data = cached.get("data", cached)
            ranked = []
            for seq_name, row in scan_data.items():
                video_path = row.get("video_path")
                usable = int(row.get("patchable_usable_bits") or 0)
                if video_path and os.path.isfile(video_path):
                    ranked.append((usable, str(video_path)))
            ranked.sort(reverse=True)
            for usable, video_path in ranked:
                if usable >= required_bits:
                    return video_path
            if ranked:
                return ranked[0][1]
        except Exception:
            pass

    best_video = None
    best_bits = -1
    for video in VIDEO_CANDIDATES:
        if os.path.isfile(video):
            try:
                stats = measure_patchable_usable_bits(video, max_positions=required_bits)
            except Exception:
                continue
            usable = int(stats["patchable_usable_bits"])
            if usable >= required_bits:
                return video
            if usable > best_bits:
                best_bits = usable
                best_video = video
    return best_video


def _validated_pool_for_video(video: str) -> list[tuple[int, int, int]]:
    required_bits = (4 + len(TEST_MSG) + 129) * 8
    contract = load_best_locked_operating_contract(required_bits=required_bits)
    if contract is None:
        return []
    if os.path.abspath(contract.video_path) != os.path.abspath(video):
        return []
    return load_sec1_positions(contract.sequence_name, validated_pool=True)


def _cleanup_output(base_path: str) -> None:
    for path in (
        base_path,
        f"{base_path}.positions.json",
        f"{base_path}.meta.json",
        f"{base_path}.manifest.json",
        ):
        if os.path.exists(path):
            os.remove(path)


def t_embed_api_sidecars_exist():
    if not node_available():
        SKIP("embed_api_sidecars_exist", "node not found on PATH")
        return

    video = _first_embeddable_video(TEST_MSG)
    if video is None:
        SKIP("embed_api_sidecars_exist", "no benchmark asset available")
        return

    out = get_output("test_p5_api_small.h264")
    try:
        candidate_pool = _validated_pool_for_video(video)
        try:
            result = embed(
                video_path=video,
                message=TEST_MSG,
                output_path=out,
                circuits_dir=CIRCUITS_DIR,
                secret_key=SECRET_KEY,
                precomputed_positions=candidate_pool or None,
                trust_precomputed_positions=False,
                use_analysis_cache=True,
            )
        except InsufficientCapacityError:
            SKIP("embed_api_sidecars_exist", "selected assets lack enough patchable capacity")
            return

        assert os.path.exists(out), "stego output file should exist"
        assert os.path.exists(f"{out}.positions.json"), "positions sidecar should exist"
        assert os.path.exists(f"{out}.meta.json"), "meta sidecar should exist"
        assert os.path.exists(f"{out}.manifest.json"), "manifest sidecar should exist"
        assert result.bits_embedded > 0, "embed() should report non-zero embedded bits"
        assert result.used_positions, "embed() should return used operating positions"
    finally:
        _cleanup_output(out)


def t_zk_full_pipeline():
    if not node_available():
        SKIP("zk_full_pipeline", "node not found on PATH")
        return

    video = _first_embeddable_video(TEST_MSG)
    if video is None:
        SKIP("zk_full_pipeline", "no benchmark asset available")
        return

    out = get_output("test_p5_zk_api.h264")
    try:
        candidate_pool = _validated_pool_for_video(video)
        try:
            result = embed(
                video_path=video,
                message=TEST_MSG,
                output_path=out,
                circuits_dir=CIRCUITS_DIR,
                secret_key=SECRET_KEY,
                precomputed_positions=candidate_pool or None,
                trust_precomputed_positions=False,
                use_analysis_cache=True,
            )
        except InsufficientCapacityError:
            SKIP("zk_full_pipeline", "selected assets lack enough patchable capacity")
            return

        verify_result = verify(
            stego_video_path=out,
            original_video_path=video,
            circuits_dir=CIRCUITS_DIR,
            secret_key=SECRET_KEY,
            message_length=len(TEST_MSG),
            precomputed_positions=result.used_positions,
            precomputed_payload_bits=result.bits_embedded,
            use_analysis_cache=True,
        )
        assert verify_result.valid, "full public API proof pipeline should verify"
        assert verify_result.message == TEST_MSG, f"unexpected extracted message: {verify_result.message!r}"
    finally:
        _cleanup_output(out)


def main():
    section("Phase 5 - Public API Round-trip & ZK Proof Verification")
    results = [
        run_test("embed_api_sidecars_exist", t_embed_api_sidecars_exist),
        run_test("zk_full_pipeline", t_zk_full_pipeline),
    ]
    sys.exit(summarise(results, "Phase 5"))


if __name__ == "__main__":
    main()
