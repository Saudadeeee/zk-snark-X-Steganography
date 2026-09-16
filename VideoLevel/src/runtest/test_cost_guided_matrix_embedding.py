"""Contracts for the controlled, low-distortion matrix-embedding mode.

The mode deliberately trades raw carrier count for fewer changed coefficients:
each seven independently CAVLC-safe carriers conveys three payload bits with at
most one coefficient change.  These tests use synthetic, already-safe blocks;
bitstream patchability remains the responsibility of CAVLCSafetyFilter.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.core.matrix_embedding import (
    MATRIX_EMBEDDING_STRATEGY,
    matrix_carrier_bit_count,
    rank_positions_cost_guided,
)
from src.core.stego import PayloadEmbedder


def _cover_with_positions(count: int):
    """Make one safe non-zero coefficient per block, across two IDR frames."""
    coefficients = []
    positions = []
    for item in range(count):
        frame_offset = 0 if item % 2 == 0 else 396
        mb = frame_offset + (item // 2)
        coeff_idx = 15 if item % 3 else 10
        coeffs = [0] * 16
        coeffs[coeff_idx] = 5 if item % 5 else -7
        coefficients.append((mb, 0, coeffs))
        positions.append((mb, 0, coeff_idx))
    return coefficients, positions


def _merged_coefficients(original, modified):
    changed = {(mb, blk): coeffs for mb, blk, coeffs in modified}
    return [(mb, blk, changed.get((mb, blk), coeffs)) for mb, blk, coeffs in original]


def t_matrix_embed_roundtrip_and_one_change_per_group():
    payload = b"matrix!"  # 56 payload bits -> 133 carriers (19 Hamming groups)
    coefficients, positions = _cover_with_positions(matrix_carrier_bit_count(len(payload) * 8))
    embedder = PayloadEmbedder(embedding_strategy=MATRIX_EMBEDDING_STRATEGY)

    modified, bits_embedded = embedder.embed_payload(
        coefficients, payload, pre_validated_positions=positions
    )

    assert bits_embedded == len(payload) * 8
    assert len(embedder.last_used_safe_positions) == matrix_carrier_bit_count(len(payload) * 8)
    assert len(embedder.last_modified_safe_positions) <= (len(payload) * 8 + 2) // 3
    assert len({(mb, blk) for mb, blk, _ in embedder.last_modified_safe_positions}) == len(embedder.last_modified_safe_positions)

    recovered = embedder.extract_payload(
        _merged_coefficients(coefficients, modified),
        len(payload) * 8,
        precomputed_safe_positions=embedder.last_used_safe_positions,
    )
    assert recovered == payload


def t_matrix_requires_full_hamming_groups():
    coefficients, positions = _cover_with_positions(20)
    embedder = PayloadEmbedder(embedding_strategy=MATRIX_EMBEDDING_STRATEGY)
    _modified, bits_embedded = embedder.embed_payload(
        coefficients, b"A", pre_validated_positions=positions
    )
    # 20 carriers hold only two complete 7-carrier groups = six payload bits.
    assert bits_embedded == 6


def t_cost_ranking_keeps_frames_interleaved_and_prefers_high_frequency():
    coefficients = [
        (0, 0, [5] + [0] * 15),
        (1, 0, [0] * 15 + [5]),
        (396, 0, [5] + [0] * 15),
        (397, 0, [0] * 15 + [5]),
    ]
    positions = [(0, 0, 0), (1, 0, 15), (396, 0, 0), (397, 0, 15)]

    ranked = rank_positions_cost_guided(positions, coefficients)

    assert [p[0] // 396 for p in ranked] == [0, 1, 0, 1]
    assert ranked[0] == (1, 0, 15)
    assert ranked[1] == (397, 0, 15)


def main():
    tests = [
        ("matrix_embed_roundtrip_and_one_change_per_group", t_matrix_embed_roundtrip_and_one_change_per_group),
        ("matrix_requires_full_hamming_groups", t_matrix_requires_full_hamming_groups),
        ("cost_ranking_keeps_frames_interleaved_and_prefers_high_frequency", t_cost_ranking_keeps_frames_interleaved_and_prefers_high_frequency),
    ]
    failures = []
    for name, test in tests:
        try:
            test()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"[FAIL] {name}: {exc}")
    if failures:
        raise SystemExit(1)
    print(f"{len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
