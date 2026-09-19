"""Contracts for sidecar-free CAVLC blind extraction."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.blind import blind_payload_bits, sign_invariant_positions
from src.runtest._helpers import run_test, section, summarise


def t_blind_positions_use_sign_only_and_keep_order():
    stable = [(17, 3, 2), (18, 5, 7), (19, 1, 1)]
    assert sign_invariant_positions(stable) == [(17, 3, ~2), (18, 5, ~7), (19, 1, ~1)]


def t_blind_payload_size_is_derivable_without_sidecar():
    # [4-byte message length][message][129-byte Groth16 proof]
    assert blind_payload_bits(message_length=13) == (4 + 13 + 129) * 8


def main():
    section("Phase 8 - Blind CAVLC Contract")
    results = [
        run_test("blind_positions_use_sign_only_and_keep_order", t_blind_positions_use_sign_only_and_keep_order),
        run_test("blind_payload_size_is_derivable_without_sidecar", t_blind_payload_size_is_derivable_without_sidecar),
    ]
    sys.exit(summarise(results, "Phase 8"))


if __name__ == "__main__":
    main()
