"""Contracts and an end-to-end test for sidecar-free CAVLC blind extraction."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.blind import (
    blind_payload_bits,
    embed_blind,
    sign_invariant_positions,
    verify_blind,
)
from src.blind_sync import BLIND_MIN_SIGN_COEFFICIENT_INDEX, build_blind_sign_candidates
from src.bitstream.bitstream_ops import _trailing_one_sign_offsets
from src.embedder import _filter_reconstructed_positions
from src.runtest._helpers import (
    get_circuits_dir,
    get_output,
    get_video,
    node_available,
    run_test,
    section,
    summarise,
    SKIP,
)


SECRET_KEY = b"blind-e2e-key-material-for-cavlc"
# Blind extraction must be validated on an asset with capacity headroom.  The
# 300-frame fixture can expose exactly 1,096 sign flags, which is only enough
# for a four-byte message plus the fixed Groth16 envelope; analysis variation
# correctly makes that edge case fail closed.  The 600-frame fixture leaves
# room for a normal integration message and exercises the same CAVLC path.
MESSAGE = b"blind-e2e"


def t_blind_positions_use_sign_only_and_keep_order():
    stable = [(17, 3, 2), (18, 5, 7), (19, 1, 1)]
    assert sign_invariant_positions(stable) == [(17, 3, ~2), (18, 5, ~7), (19, 1, ~1)]
    # Already-tagged CAVLC sign positions are an idempotent representation.
    assert sign_invariant_positions([(20, 2, ~4)]) == [(20, 2, ~4)]


def t_blind_payload_size_is_derivable_without_sidecar():
    # [4-byte message length][message][129-byte Groth16 proof]
    assert blind_payload_bits(message_length=13) == (4 + 13 + 129) * 8


def t_reconstruction_accounting_excludes_unapplied_blocks():
    used = [(10, 0, ~2), (11, 1, ~3)]
    filtered, missing = _filter_reconstructed_positions(
        used_positions=used,
        modified_block_keys={(10, 0), (11, 1)},
        applied_block_keys={(10, 0)},
    )
    assert filtered == [(10, 0, ~2)]
    assert missing == {(11, 1)}


def t_blind_candidates_only_use_validated_cavlc_sign_positions():
    safe_positions = [
        (9, 0, ~0),
        (10, 0, 3),
        (10, 0, ~7),
        (10, 0, ~9),
        (11, 1, ~2),
        (12, 2, 4),
    ]
    # One sign position per block prevents a second bit from changing the same
    # CAVLC block and preserves the extraction schedule.
    assert build_blind_sign_candidates(safe_positions) == [(10, 0, ~7), (11, 1, ~2)]


def t_blind_candidates_exclude_signs_that_cannot_be_patched_in_both_states():
    safe_positions = [(10, 0, ~2), (11, 1, ~3), (12, 2, ~4)]
    patchable = {(10, 0, ~2), (12, 2, ~4)}
    assert build_blind_sign_candidates(
        safe_positions,
        is_flip_patchable=lambda pos: pos in patchable,
    ) == [(10, 0, ~2), (12, 2, ~4)]


def t_blind_candidates_can_require_high_frequency_ac_signs():
    safe_positions = [(10, 0, ~7), (11, 1, ~8), (12, 2, ~12)]
    assert build_blind_sign_candidates(safe_positions, min_coefficient_index=8) == [
        (11, 1, ~8),
        (12, 2, ~12),
    ]


def t_blind_operating_point_excludes_the_lowest_ac_band():
    assert BLIND_MIN_SIGN_COEFFICIENT_INDEX == 7


def t_blind_sign_patch_targets_only_the_cavlc_sign_flag():
    # nC=0, TotalCoeff=1, TrailingOnes=1: coeff_token is three bits, followed
    # by the one-bit trailing-one sign flag.
    assert _trailing_one_sign_offsets(bytes([0b00010100]), 0, nC=0, max_num_coeff=16) == [3]


def _remove_blind_artifacts(output_path: str) -> None:
    for suffix in ("", ".positions.json", ".meta.json", ".manifest.json", ".lattice.json"):
        artifact = Path(f"{output_path}{suffix}")
        if artifact.exists():
            artifact.unlink()


def t_blind_round_trip_without_cover_or_sidecars():
    if not node_available():
        SKIP("blind_round_trip_without_cover_or_sidecars", "node not found on PATH")
        return

    video = get_video("deadline_cif_q22_g1_600f.h264")
    if not os.path.isfile(video):
        SKIP("blind_round_trip_without_cover_or_sidecars", "blind E2E video asset unavailable")
        return

    output = get_output("test_p8_blind_e2e.h264")
    _remove_blind_artifacts(output)
    try:
        embedded = embed_blind(
            video_path=video,
            message=MESSAGE,
            output_path=output,
            circuits_dir=get_circuits_dir(),
            secret_key=SECRET_KEY,
            use_analysis_cache=True,
        )
        assert os.path.isfile(output), "blind embed must produce a stego bitstream"
        assert embedded.bits_embedded == blind_payload_bits(message_length=len(MESSAGE))

        # A blind receiver must not use the original cover or any generated sidecar.
        for suffix in (".positions.json", ".meta.json", ".manifest.json", ".lattice.json"):
            sidecar = Path(f"{output}{suffix}")
            if sidecar.exists():
                sidecar.unlink()

        verified = verify_blind(
            stego_video_path=output,
            circuits_dir=get_circuits_dir(),
            secret_key=SECRET_KEY,
            message_length=len(MESSAGE),
            use_analysis_cache=True,
        )
        assert verified.valid, "blind verification must succeed without cover or sidecars"
        assert verified.message == MESSAGE
    finally:
        _remove_blind_artifacts(output)


def main():
    section("Phase 8 - Blind CAVLC Contract")
    results = [
        run_test("blind_positions_use_sign_only_and_keep_order", t_blind_positions_use_sign_only_and_keep_order),
        run_test("blind_payload_size_is_derivable_without_sidecar", t_blind_payload_size_is_derivable_without_sidecar),
        run_test("reconstruction_accounting_excludes_unapplied_blocks", t_reconstruction_accounting_excludes_unapplied_blocks),
        run_test("blind_candidates_only_use_validated_cavlc_sign_positions", t_blind_candidates_only_use_validated_cavlc_sign_positions),
        run_test("blind_candidates_exclude_signs_that_cannot_be_patched_in_both_states", t_blind_candidates_exclude_signs_that_cannot_be_patched_in_both_states),
        run_test("blind_candidates_can_require_high_frequency_ac_signs", t_blind_candidates_can_require_high_frequency_ac_signs),
        run_test("blind_operating_point_excludes_the_lowest_ac_band", t_blind_operating_point_excludes_the_lowest_ac_band),
        run_test("blind_sign_patch_targets_only_the_cavlc_sign_flag", t_blind_sign_patch_targets_only_the_cavlc_sign_flag),
        run_test("blind_round_trip_without_cover_or_sidecars", t_blind_round_trip_without_cover_or_sidecars),
    ]
    sys.exit(summarise(results, "Phase 8"))


if __name__ == "__main__":
    main()
