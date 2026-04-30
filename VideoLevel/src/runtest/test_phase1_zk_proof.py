"""
test_phase1_zk_proof.py — Phase 1: ZK-SNARK Proof Generation, Serialization, Verification

Tests:
  1. pack_unpack_roundtrip        — pack/unpack preserves message and proof bytes
  2. proof_bytes_roundtrip        — proof_to_bytes / bytes_to_proof is lossless
  3. proof_size_129               — serialized proof is exactly 129 bytes
  4. blob_bit_length_formula      — blob_bit_length = (4 + len(msg) + 129) * 8
  5. zk_generate_and_verify       — real Groth16 proof generation + verification (needs node)
  6. zk_tampered_message_fails    — verification with wrong payload returns False (needs node)

Run:
    python src/runtest/test_phase1_zk_proof.py
"""

import os
import sys

# Allow running directly from project root or via run_all.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.runtest._helpers import (
    section, run_test, summarise, SKIP,
    get_circuits_dir, node_available,
)

from src.zk_proof import (
    pack, unpack, proof_to_bytes, bytes_to_proof, blob_bit_length,
    PROOF_SIZE_BYTES,
)

# ── Fixtures ──────────────────────────────────────────────────────────── #

SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"   # 32 bytes
TEST_MSG   = b"Hello ZK-Stego"

# Minimal structurally-valid fake proof dict (snarkjs JSON format)
def _fake_proof() -> dict:
    """Build a deterministic fake 129-byte serialisable proof dict.
    Values must be decimal strings (snarkjs proof format uses base-10 integers).
    """
    return {
        "pi_a": ["1", "2", "1"],
        "pi_b": [["3", "4"], ["5", "6"], ["1", "0"]],
        "pi_c": ["7", "8", "1"],
        "protocol": "groth16",
        "curve": "bn128",
    }

_FAKE_PROOF_BYTES = proof_to_bytes(_fake_proof())


# ── Test cases ────────────────────────────────────────────────────────── #

def t_pack_unpack_roundtrip():
    blob = pack(TEST_MSG, _FAKE_PROOF_BYTES)
    msg_out, proof_out = unpack(blob)
    assert msg_out == TEST_MSG,          f"message mismatch: {msg_out!r} != {TEST_MSG!r}"
    assert proof_out == _FAKE_PROOF_BYTES, "proof bytes mismatch after unpack"


def t_proof_bytes_roundtrip():
    original = _fake_proof()
    raw      = proof_to_bytes(original)
    restored = bytes_to_proof(raw)
    # Compressed format stores only X coordinate; Y is recomputed from BN128 curve.
    # pi_a=(1,2): 1^3+3=4, sqrt(4)=2 — valid curve point, Y roundtrips.
    # pi_c=(7,8): not a valid curve point — only X is preserved.
    assert int(restored["pi_a"][0], 16) == int(original["pi_a"][0], 16)
    assert int(restored["pi_a"][1], 16) == int(original["pi_a"][1], 16)
    assert int(restored["pi_c"][0], 16) == int(original["pi_c"][0], 16)
    # pi_c Y is recomputed from curve; skip comparison for off-curve fake value


def t_proof_size_129():
    raw = proof_to_bytes(_fake_proof())
    assert len(raw) == PROOF_SIZE_BYTES, \
        f"proof size {len(raw)} != {PROOF_SIZE_BYTES}"


def t_blob_bit_length_formula():
    for msg in [b"", b"hi", b"Hello ZK-Stego", b"x" * 50]:
        expected = (4 + len(msg) + PROOF_SIZE_BYTES) * 8
        got      = blob_bit_length(msg)
        assert got == expected, \
            f"blob_bit_length({len(msg)}B msg) = {got}, expected {expected}"


def t_blob_structure():
    msg   = b"test message"
    proof = _FAKE_PROOF_BYTES
    blob  = pack(msg, proof)
    # First 4 bytes = big-endian length of message
    import struct
    length_field = struct.unpack(">I", blob[:4])[0]
    assert length_field == len(msg), \
        f"header length field {length_field} != {len(msg)}"
    # Total blob length
    assert len(blob) == 4 + len(msg) + PROOF_SIZE_BYTES


def t_zk_generate_and_verify():
    if not node_available():
        SKIP("zk_generate_and_verify", "node not found on PATH")
        return
    circuits = get_circuits_dir()
    from src.zk_proof import ZKSnarkBridge
    bridge = ZKSnarkBridge(circuits)
    proof_dict, public_dict = bridge.generate_proof_for_payload(TEST_MSG, SECRET_KEY)
    assert isinstance(proof_dict, dict), "proof_dict must be a dict"
    assert "pi_a" in proof_dict and "pi_c" in proof_dict, "proof missing pi_a/pi_c"
    ok = bridge.verify(proof_dict, public_dict)
    assert ok, "Groth16 verify returned False for a freshly-generated proof"


def t_zk_tampered_message_fails():
    if not node_available():
        SKIP("zk_tampered_message_fails", "node not found on PATH")
        return
    circuits = get_circuits_dir()
    from src.zk_proof import ZKSnarkBridge
    bridge = ZKSnarkBridge(circuits)
    proof_dict, _ = bridge.generate_proof_for_payload(TEST_MSG, SECRET_KEY)
    # Build public signals for a DIFFERENT message
    tampered     = b"tampered payload"
    public_wrong = bridge._build_public_signals(tampered, SECRET_KEY)
    ok = bridge.verify(proof_dict, public_wrong)
    assert not ok, "verify should return False for tampered message"


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    section("Phase 1 — ZK-SNARK Proof: Format, Serialization, Verification")
    results = [
        run_test("pack_unpack_roundtrip",     t_pack_unpack_roundtrip),
        run_test("proof_bytes_roundtrip",     t_proof_bytes_roundtrip),
        run_test("proof_size_129",            t_proof_size_129),
        run_test("blob_bit_length_formula",   t_blob_bit_length_formula),
        run_test("blob_structure",            t_blob_structure),
        run_test("zk_generate_and_verify",    t_zk_generate_and_verify),
        run_test("zk_tampered_message_fails", t_zk_tampered_message_fails),
    ]
    sys.exit(summarise(results, "Phase 1"))


if __name__ == '__main__':
    main()
