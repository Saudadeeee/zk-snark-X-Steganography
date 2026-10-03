"""
test_zk_proof.py — ZK-SNARK Proof Generation, Serialization, Verification

Tests:
  1. pack_unpack_roundtrip        — pack/unpack preserves message and proof bytes
  2. proof_bytes_roundtrip        — proof_to_bytes / bytes_to_proof is lossless
  3. proof_size_129               — serialized proof is exactly 129 bytes
  4. blob_bit_length_formula      — blob_bit_length = (4 + len(msg) + 129) * 8
  5. zk_generate_and_verify       — real Groth16 proof generation + verification (needs node)
  6. zk_tampered_message_fails    — verification with wrong payload returns False (needs node)

Run:
    python src/runtest/test_zk_proof.py
"""

import os
import sys
from unittest.mock import patch

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

_BN254_P = 21888242871839275222246405745257275088696311157297823662689037894645226208583
_G2_X = ["10857046999023057135944570762232829481370756359578518086990519993285655852781",
         "11559732032986387107991004021392285783925812861821192530917403151452391805634"]
_G2_Y = ["8495653923123431417604973247489272438418190587263600148770280649306958101930",
         "4082367875863433681332203403145435568316851327593401208105741076214120093531"]


# Structurally valid, on-curve fake proof dict (snarkjs JSON format).
def _fake_proof() -> dict:
    """Build a deterministic 129-byte serialisable proof from BN254 generators.
    pi_a = G1, pi_b = G2, pi_c = -G1. Values are decimal strings as in snarkjs.
    """
    return {
        "pi_a": ["1", "2", "1"],
        "pi_b": [list(_G2_X), list(_G2_Y), ["1", "0"]],
        "pi_c": ["1", str(_BN254_P - 2), "1"],
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
    # Compressed format stores X plus a Y-parity flag; Y is recomputed on the curve.
    assert restored["pi_a"][:2] == original["pi_a"][:2]
    assert restored["pi_c"][:2] == original["pi_c"][:2]
    assert restored["pi_b"][:2] == original["pi_b"][:2]


def t_bytes_to_proof_rejects_malformed():
    raw = bytearray(_FAKE_PROOF_BYTES)
    off_curve = bytearray(raw)
    # Smallest x where x^3+3 is a quadratic non-residue, i.e. no G1 point exists.
    x_off = next(x for x in range(2, 100)
                 if pow((x ** 3 + 3) % _BN254_P, (_BN254_P - 1) // 2, _BN254_P) != 1)
    off_curve[0:32] = x_off.to_bytes(32, "big")
    non_canonical = bytearray(raw)
    non_canonical[0:32] = (_BN254_P + 1).to_bytes(32, "big")
    bad_flags = bytearray(raw)
    bad_flags[128] |= 0x80
    for label, candidate in (
        ("short", bytes(raw[:-1])),
        ("off_curve", bytes(off_curve)),
        ("non_canonical", bytes(non_canonical)),
        ("bad_flags", bytes(bad_flags)),
    ):
        try:
            bytes_to_proof(candidate)
        except ValueError:
            continue
        raise AssertionError(f"bytes_to_proof accepted malformed input: {label}")


def t_snarkjs_verify_fails_closed():
    """Verification must depend on the exit code, never on output substrings."""
    import subprocess
    from src.zk_proof import ZKSnarkBridge

    bridge = ZKSnarkBridge(get_circuits_dir())
    cases = (
        (1, "Unexpected token in JSON, ok\n", False),          # crash text containing "ok"
        (0, "[INFO]  snarkJS: something else\n", False),        # exit 0 without OK!
        (1, "[INFO]  snarkJS: OK!\n", False),                   # OK! but failing exit code
        (0, "[INFO]  snarkJS: OK!\n", True),
    )
    for returncode, stdout, expected in cases:
        completed = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with patch.object(bridge, "_run_snarkjs", return_value=completed):
            got = bridge._snarkjs_verify(_fake_proof(), ["1"])
        assert got is expected, f"returncode={returncode} stdout={stdout!r}: got {got}"


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


def t_verify_proof_for_payload_public_api():
    from src.zk_proof import ZKSnarkBridge

    bridge = ZKSnarkBridge(get_circuits_dir())
    message, key, proof = b"client API payload", b"k" * 32, {"proof": "fixture"}
    public_signals = bridge._build_public_signals(message, key)
    with patch.object(bridge, "verify", return_value=True) as verify:
        assert bridge.verify_proof_for_payload(proof, message, key)
        verify.assert_called_once_with(proof, public_signals)

    for invalid_message, invalid_key in ((b"", key), (message, b"short")):
        try:
            bridge.verify_proof_for_payload(proof, invalid_message, invalid_key)
        except ValueError:
            continue
        raise AssertionError("proof verification must reject empty messages and non-32-byte keys")


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
    assert bridge.verify_proof_for_payload(proof_dict, TEST_MSG, SECRET_KEY), \
        "public proof-payload verification failed for a freshly-generated proof"
    assert public_dict[-1] == str(len(TEST_MSG)), \
        "Groth16 public signal order must place payload length last"
    altered_public = list(public_dict)
    altered_public[-1] = str(int(altered_public[-1]) + 1)
    assert not bridge.verify(proof_dict, altered_public), \
        "Groth16 proof unexpectedly verified with a modified public payload length"


def t_zk_tampered_message_fails():
    if not node_available():
        SKIP("zk_tampered_message_fails", "node not found on PATH")
        return
    circuits = get_circuits_dir()
    from src.zk_proof import ZKSnarkBridge
    bridge = ZKSnarkBridge(circuits)
    proof_dict, _ = bridge.generate_proof_for_payload(TEST_MSG, SECRET_KEY)
    tampered     = b"tampered payload"
    ok = bridge.verify_proof_for_payload(proof_dict, tampered, SECRET_KEY)
    assert not ok, "verify should return False for tampered message"


def t_zk_rejects_invalid_payload_lengths():
    if not node_available():
        SKIP("zk_rejects_invalid_payload_lengths", "node not found on PATH")
        return
    circuits = get_circuits_dir()
    from src.zk_proof import ZKSnarkBridge
    bridge = ZKSnarkBridge(circuits)
    for invalid_payload in (b"", b"x" * 1_000_000):
        try:
            bridge.generate_proof_for_payload(invalid_payload, SECRET_KEY)
        except RuntimeError:
            continue
        raise AssertionError(f"payload length {len(invalid_payload)} unexpectedly produced a proof")


# ── Main ─────────────────────────────────────────────────────────────── #

def main():
    section("ZK proof: format, serialization, verification")
    results = [
        run_test("pack_unpack_roundtrip",     t_pack_unpack_roundtrip),
        run_test("proof_bytes_roundtrip",     t_proof_bytes_roundtrip),
        run_test("bytes_to_proof_rejects_malformed", t_bytes_to_proof_rejects_malformed),
        run_test("snarkjs_verify_fails_closed", t_snarkjs_verify_fails_closed),
        run_test("proof_size_129",            t_proof_size_129),
        run_test("blob_bit_length_formula",   t_blob_bit_length_formula),
        run_test("blob_structure",            t_blob_structure),
        run_test("verify_proof_for_payload_public_api", t_verify_proof_for_payload_public_api),
        run_test("zk_generate_and_verify",    t_zk_generate_and_verify),
        run_test("zk_tampered_message_fails", t_zk_tampered_message_fails),
        run_test("zk_rejects_invalid_payload_lengths", t_zk_rejects_invalid_payload_lengths),
    ]
    sys.exit(summarise(results, "ZK proof"))


if __name__ == '__main__':
    main()
