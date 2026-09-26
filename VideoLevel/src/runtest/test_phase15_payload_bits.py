"""Exact-bit payload embedding contracts for streaming carrier chunks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.stego import PayloadEmbedder
from src.runtest._helpers import run_test, section, summarise


def _tiny_coefficients() -> tuple[list[tuple[int, int, list[int]]], list[tuple[int, int, int]]]:
    coefficients = [
        (0, 0, [0, 4, 2] + [0] * 13),
        (0, 1, [0, 4, 2] + [0] * 13),
        (1, 0, [0, 4, 2] + [0] * 13),
    ]
    positions = [(0, 0, 1), (0, 1, 1), (1, 0, 1)]
    return coefficients, positions


def t_embed_bits_preserves_non_byte_aligned_length() -> None:
    coefficients, positions = _tiny_coefficients()
    embedder = PayloadEmbedder(max_modifications_per_block=1)

    modified, embedded = embedder.embed_bits(
        coefficients,
        [1, 0, 1],
        pre_validated_positions=positions,
    )

    assert embedded == 3
    assert embedder.last_used_safe_positions == positions
    updated_map = {(mb, block): values for mb, block, values in coefficients}
    updated_map.update({(mb, block): values for mb, block, values in modified})
    assert [updated_map[(mb, block)][1] & 1 for mb, block, _ in positions] == [1, 0, 1]


def t_embed_bits_rejects_non_binary_values() -> None:
    coefficients, positions = _tiny_coefficients()
    embedder = PayloadEmbedder(max_modifications_per_block=1)

    try:
        embedder.embed_bits(coefficients, [0, 2], pre_validated_positions=positions)
    except ValueError as error:
        assert "0 or 1" in str(error)
    else:
        raise AssertionError("non-binary payload bit was accepted")


def t_payload_bit_tests_are_registered_in_full_runner() -> None:
    from src.runtest.run_all import PHASES

    assert any(filename == "test_phase15_payload_bits.py" for _, _, filename in PHASES)


def main() -> None:
    section("Phase 15 - Exact-bit payload embedding")
    results = [
        run_test("embed_bits_preserves_non_byte_aligned_length", t_embed_bits_preserves_non_byte_aligned_length),
        run_test("embed_bits_rejects_non_binary_values", t_embed_bits_rejects_non_binary_values),
        run_test("payload_bit_tests_are_registered_in_full_runner", t_payload_bit_tests_are_registered_in_full_runner),
    ]
    raise SystemExit(summarise(results, "Phase 15"))


if __name__ == "__main__":
    main()
