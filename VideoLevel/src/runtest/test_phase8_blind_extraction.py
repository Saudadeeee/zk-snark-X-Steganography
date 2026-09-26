"""Contracts and an end-to-end test for sidecar-free CAVLC blind extraction."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.blind import (
    blind_payload_bits,
    sign_invariant_positions,
)
from src.blind_sync import (
    BLIND_MIN_SIGN_COEFFICIENT_INDEX,
    _filter_flip_patchable_sign_candidates,
    build_blind_sign_candidates,
)
from src.bitstream.bitstream_ops import _trailing_one_sign_offsets
from src.embedder import _filter_reconstructed_positions
from src.embedder import _resolve_video_analysis
from src.core.stego import PayloadEmbedder
from src.runtest._helpers import (
    run_test,
    section,
    summarise,
)


def t_blind_positions_use_sign_only_and_keep_order():
    stable = [(17, 3, 2), (18, 5, 7), (19, 1, 1)]
    assert sign_invariant_positions(stable) == [(17, 3, ~2), (18, 5, ~7), (19, 1, ~1)]
    # Already-tagged CAVLC sign positions are an idempotent representation.
    assert sign_invariant_positions([(20, 2, ~4)]) == [(20, 2, ~4)]


def t_blind_payload_size_is_derivable_without_sidecar():
    # [4-byte message length][message][129-byte Groth16 proof]
    assert blind_payload_bits(message_length=13) == (4 + 13 + 129) * 8


def t_prevalidated_embed_materializes_only_selected_blocks():
    coefficients = [(mb, 0, [1] + [0] * 15) for mb in range(128)]
    embedder = PayloadEmbedder(max_modifications_per_block=1)
    modified, bits_embedded = embedder.embed_payload(
        coefficients,
        b"\x80",
        pre_validated_positions=[(127, 0, ~0)],
    )
    assert bits_embedded == 1
    assert modified == [(127, 0, [-1] + [0] * 15)]


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


def t_blind_candidate_filter_uses_direct_global_block_lookup():
    class GetOnlyDict(dict):
        def items(self):
            raise AssertionError("blind candidate filtering must not copy every block map")

    coefficients = [(100, 0, [0, 0, 0, 0, 0, 0, 0, 1])]
    frame_verified_data = {
        100: (
            GetOnlyDict({(100, 0): {"start_bit": 0}}),
            GetOnlyDict({(100, 0): [0, 0, 0, 0, 0, 0, 0, 1]}),
            b"",
        )
    }
    assert _filter_flip_patchable_sign_candidates(
        [(100, 0, ~7)],
        coefficients=coefficients,
        frame_verified_data=frame_verified_data,
        required_bits=1,
    ) == [(100, 0, ~7)]


def t_embed_analysis_resolver_reuses_supplied_analysis_without_loading():
    supplied = ([], {}, {}, {}, {}, [])
    assert _resolve_video_analysis(
        "unused.h264",
        use_analysis_cache=True,
        force_analysis_refresh=False,
        analysis_cache_dir=None,
        precomputed_analysis=supplied,
    ) is supplied


def t_blind_candidates_can_require_high_frequency_ac_signs():
    safe_positions = [(10, 0, ~7), (11, 1, ~8), (12, 2, ~12)]
    assert build_blind_sign_candidates(safe_positions, min_coefficient_index=8) == [
        (11, 1, ~8),
        (12, 2, ~12),
    ]


def t_blind_operating_point_excludes_the_lowest_ac_band():
    assert BLIND_MIN_SIGN_COEFFICIENT_INDEX == 7


def t_blind_sign_patch_targets_only_the_cavlc_sign_flag():
    # nC=0, TotalCoeff=1, TrailingOnes=1: coeff_token is two bits, followed
    # by the one-bit trailing-one sign flag.
    assert _trailing_one_sign_offsets(bytes.fromhex("4180"), 0, nC=0, max_num_coeff=16) == [2]


def t_native_websocket_blind_fixture_round_trip():
    """Exercise the deployed native CAVLC blind channel, not Python fallback."""
    from src.runtest.test_native_http_channel import t_native_authenticated_websocket_live_round_trip

    t_native_authenticated_websocket_live_round_trip()


def main():
    section("Phase 8 - Blind CAVLC Contract")
    results = [
        run_test("blind_positions_use_sign_only_and_keep_order", t_blind_positions_use_sign_only_and_keep_order),
        run_test("blind_payload_size_is_derivable_without_sidecar", t_blind_payload_size_is_derivable_without_sidecar),
        run_test("prevalidated_embed_materializes_only_selected_blocks", t_prevalidated_embed_materializes_only_selected_blocks),
        run_test("reconstruction_accounting_excludes_unapplied_blocks", t_reconstruction_accounting_excludes_unapplied_blocks),
        run_test("blind_candidates_only_use_validated_cavlc_sign_positions", t_blind_candidates_only_use_validated_cavlc_sign_positions),
        run_test("blind_candidates_exclude_signs_that_cannot_be_patched_in_both_states", t_blind_candidates_exclude_signs_that_cannot_be_patched_in_both_states),
        run_test("blind_candidate_filter_uses_direct_global_block_lookup", t_blind_candidate_filter_uses_direct_global_block_lookup),
        run_test("embed_analysis_resolver_reuses_supplied_analysis_without_loading", t_embed_analysis_resolver_reuses_supplied_analysis_without_loading),
        run_test("blind_candidates_can_require_high_frequency_ac_signs", t_blind_candidates_can_require_high_frequency_ac_signs),
        run_test("blind_operating_point_excludes_the_lowest_ac_band", t_blind_operating_point_excludes_the_lowest_ac_band),
        run_test("blind_sign_patch_targets_only_the_cavlc_sign_flag", t_blind_sign_patch_targets_only_the_cavlc_sign_flag),
        run_test("native_websocket_blind_fixture_round_trip", t_native_websocket_blind_fixture_round_trip),
    ]
    sys.exit(summarise(results, "Phase 8"))


if __name__ == "__main__":
    main()
