"""
Minimal public API demo for locked artifact verify().

Exit codes:
  0 = demo ran and proof verified
  1 = unexpected failure or verification failure
  2 = required capacity/artifacts are unavailable in this checkout
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.locked_operating_contract import (
    LOCKED_CHAOS_KEY,
    LOCKED_MESSAGE,
    LOCKED_SECRET_KEY,
    load_best_locked_operating_contract,
)
from src.runtest._helpers import get_circuits_dir, node_available
from src.verifier import verify


def main() -> int:
    if not node_available():
        print("[INCOMPLETE] node is not available on PATH")
        return 2

    circuits_dir = get_circuits_dir()
    if not Path(circuits_dir).exists():
        print(f"[INCOMPLETE] circuits directory missing: {circuits_dir}")
        return 2

    required_bits = (4 + len(LOCKED_MESSAGE) + 129) * 8
    contract = load_best_locked_operating_contract(required_bits=required_bits)
    if contract is None:
        print("[INCOMPLETE] no verified locked operating contract is available")
        return 2

    verify_result = verify(
        stego_video_path=contract.stego_path,
        original_video_path=contract.video_path,
        circuits_dir=circuits_dir,
        secret_key=LOCKED_SECRET_KEY,
        message_length=len(LOCKED_MESSAGE),
        chaos_key=LOCKED_CHAOS_KEY,
        precomputed_positions=contract.positions,
        precomputed_payload_bits=contract.bits_embedded,
        use_analysis_cache=True,
    )
    if not verify_result.valid or verify_result.message != LOCKED_MESSAGE:
        print("[FAIL] locked artifact did not verify")
        return 1
    print(
        "[PASS] locked artifact verify "
        f"sequence={contract.sequence_name} bits={contract.bits_embedded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
