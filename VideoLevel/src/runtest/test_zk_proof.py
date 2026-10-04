"""
test_zk_proof.py — camera proof: proof format, payload, Poseidon, registry, binding, Groth16.

The statement (circuits/camera_video.circom): a camera registered under a public
Merkle root vouches for a binding of the video digest and the message. Real
proving/verifying needs Node.js and the keys from ``py -3.12 -m src.zk_setup``.

Run:
    python src/runtest/test_zk_proof.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Allow running directly from project root or via run_all.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.camera_registry import (
    CameraRegistry,
    camera_public_key,
    load_camera_secret,
    new_camera_secret,
    save_camera_secret,
)
from src.poseidon import FIELD_MODULUS, poseidon
from src.runtest._helpers import SKIP, get_circuits_dir, node_available, run_test, section, summarise
from src.video_binding import (
    MODE_MESSAGE_ONLY,
    MODE_VIDEO,
    binding_digest,
    binding_public_inputs,
)
from src.zk_proof import (
    PROOF_SIZE_BYTES,
    CameraProofBridge,
    bytes_to_proof,
    pack_payload,
    payload_size,
    proof_to_bytes,
    unpack_payload,
)

_BN254_P = 21888242871839275222246405745257275088696311157297823662689037894645226208583
_G2_X = ["10857046999023057135944570762232829481370756359578518086990519993285655852781",
         "11559732032986387107991004021392285783925812861821192530917403151452391805634"]
_G2_Y = ["8495653923123431417604973247489272438418190587263600148770280649306958101930",
         "4082367875863433681332203403145435568316851327593401208105741076214120093531"]
MESSAGE = b"Hello ZK-Stego"
DIGEST = bytes(range(32))


def _fake_proof() -> dict:
    """Structurally valid, on-curve proof dict: pi_a = G1, pi_b = G2, pi_c = -G1."""
    return {"pi_a": ["1", "2", "1"], "pi_b": [list(_G2_X), list(_G2_Y), ["1", "0"]],
            "pi_c": ["1", str(_BN254_P - 2), "1"], "protocol": "groth16", "curve": "bn128"}


_FAKE_PROOF_BYTES = proof_to_bytes(_fake_proof())


def _expect_value_error(operation, label: str) -> None:
    try:
        operation()
    except ValueError:
        return
    raise AssertionError(f"{label}: expected ValueError")


def _bridge_or_skip(name: str) -> CameraProofBridge:
    bridge = CameraProofBridge(get_circuits_dir())
    if not node_available() or not all(path.is_file() for path in bridge.required_files()):
        SKIP(name, "node or camera_video keys missing (py -3.12 -m src.zk_setup)")
    return bridge


# ── Proof binary form ─────────────────────────────────────────────────── #

def t_proof_bytes_roundtrip():
    original = _fake_proof()
    raw = proof_to_bytes(original)
    assert len(raw) == PROOF_SIZE_BYTES
    restored = bytes_to_proof(raw)
    # Compressed form stores X plus a Y-parity flag; Y is recomputed on the curve.
    for key in ("pi_a", "pi_b", "pi_c"):
        assert restored[key][:2] == original[key][:2], key


def t_bytes_to_proof_rejects_malformed():
    raw = bytearray(_FAKE_PROOF_BYTES)
    off_curve = bytearray(raw)
    # Smallest x where x^3+3 is a quadratic non-residue, i.e. no G1 point exists.
    x_off = next(x for x in range(2, 100) if pow((x ** 3 + 3) % _BN254_P, (_BN254_P - 1) // 2, _BN254_P) != 1)
    off_curve[0:32] = x_off.to_bytes(32, "big")
    non_canonical = bytearray(raw)
    non_canonical[0:32] = (_BN254_P + 1).to_bytes(32, "big")
    bad_flags = bytearray(raw)
    bad_flags[128] |= 0x80
    for label, candidate in (("short", bytes(raw[:-1])), ("off_curve", bytes(off_curve)),
                             ("non_canonical", bytes(non_canonical)), ("bad_flags", bytes(bad_flags))):
        _expect_value_error(lambda candidate=candidate: bytes_to_proof(candidate), label)


def t_snarkjs_verify_fails_closed():
    """Verification depends on exit code AND the OK! line, never on substrings alone."""
    bridge = CameraProofBridge(get_circuits_dir())
    cases = ((1, "Unexpected token in JSON, ok\n", False), (0, "[INFO]  snarkJS: something else\n", False),
             (1, "[INFO]  snarkJS: OK!\n", False), (0, "[INFO]  snarkJS: OK!\n", True))
    for returncode, stdout, expected in cases:
        completed = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with patch.object(bridge, "_run_snarkjs", return_value=completed):
            got = bridge._snarkjs_verify(_fake_proof(), ["1"])
        assert got is expected, f"returncode={returncode} stdout={stdout!r}: got {got}"


# ── Payload ───────────────────────────────────────────────────────────── #

def t_payload_roundtrip_and_layout():
    for mode in (MODE_VIDEO, MODE_MESSAGE_ONLY):
        for message in (b"", MESSAGE, b"x" * 300):
            blob = pack_payload(mode, message, _FAKE_PROOF_BYTES)
            assert len(blob) == payload_size(len(message)) == 4 + len(message) + PROOF_SIZE_BYTES
            assert blob[0] == 0x01 and blob[1] == mode and int.from_bytes(blob[2:4], "big") == len(message)
            unpacked = unpack_payload(blob)
            assert (unpacked.mode, unpacked.message, unpacked.proof_bytes) == (mode, message, _FAKE_PROOF_BYTES)


def t_payload_rejects_other_layouts():
    blob = pack_payload(MODE_VIDEO, MESSAGE, _FAKE_PROOF_BYTES)
    for label, candidate in (("short", blob[:3]), ("format", b"\x02" + blob[1:]), ("mode", blob[:1] + b"\x05" + blob[2:]),
                             ("trailing", blob + b"x"), ("truncated", blob[:-1])):
        _expect_value_error(lambda candidate=candidate: unpack_payload(candidate), label)
    _expect_value_error(lambda: pack_payload(2, MESSAGE, _FAKE_PROOF_BYTES), "pack mode")
    _expect_value_error(lambda: pack_payload(MODE_VIDEO, MESSAGE, _FAKE_PROOF_BYTES[:-1]), "pack proof size")


# ── Poseidon, registry, binding ───────────────────────────────────────── #

def t_poseidon_matches_circomlib_vectors():
    # circomlibjs reference vectors for poseidon([1]) and poseidon([1, 2]).
    assert hex(poseidon([1])) == "0x29176100eaa962bdc1fe6c654d6a3c130e96a4d1168b33848b897dc502820133"
    assert hex(poseidon([1, 2])) == "0x115cc0f5e7d690413df64c6b9662e9cf2a3617f2743245519e19607a4417189a"
    # Shared with circuits/test/circuits.test.js: secret 1 opened along 16 levels of zero siblings.
    node = camera_public_key(1)
    for _ in range(16):
        node = poseidon([node, 0])
    assert node == 13540250208624962443651359021534662279818360331845733678151493660599986427279
    _expect_value_error(lambda: poseidon([FIELD_MODULUS]), "input outside the field")
    _expect_value_error(lambda: poseidon([1, 2, 3]), "three inputs")


def t_registry_paths_rebuild_the_root():
    camera_secrets = [new_camera_secret() for _ in range(5)]
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    for index, secret in enumerate(camera_secrets):
        path = registry.path(index)
        node = camera_public_key(secret)
        for sibling, right in zip(path.siblings, path.path_indices):
            node = poseidon([sibling, node]) if right else poseidon([node, sibling])
        assert node == registry.root, index
    assert CameraRegistry.from_json(registry.to_json()).root == registry.root
    tampered = registry.to_json()
    tampered["public_keys"][0] = hex(camera_public_key(new_camera_secret()))
    _expect_value_error(lambda: CameraRegistry.from_json(tampered), "root mismatch")
    _expect_value_error(lambda: registry.index_of(camera_public_key(new_camera_secret())), "unregistered")
    _expect_value_error(lambda: CameraRegistry([1, 1]), "duplicate key")
    with tempfile.TemporaryDirectory() as temp_dir:
        secret_path = Path(temp_dir) / "camera.json"
        save_camera_secret(camera_secrets[0], secret_path)
        assert load_camera_secret(secret_path) == camera_secrets[0]
        try:
            save_camera_secret(camera_secrets[1], secret_path)
        except FileExistsError:
            pass
        else:
            raise AssertionError("a camera secret file must never be overwritten")


def t_binding_rules():
    video = binding_digest(MODE_VIDEO, DIGEST, MESSAGE)
    assert video != binding_digest(MODE_VIDEO, DIGEST, MESSAGE + b"!")
    assert video != binding_digest(MODE_VIDEO, bytes(32), MESSAGE)
    message_only = binding_digest(MODE_MESSAGE_ONLY, bytes(32), MESSAGE)
    assert message_only != binding_digest(MODE_VIDEO, bytes(32), MESSAGE)  # the mode is bound too
    _expect_value_error(lambda: binding_digest(MODE_MESSAGE_ONLY, DIGEST, MESSAGE), "message-only digest")
    _expect_value_error(lambda: binding_digest(2, DIGEST, MESSAGE), "mode")
    high, low = binding_public_inputs(video)
    assert high < 1 << 128 and low < 1 << 128 and (high << 128 | low) == int.from_bytes(video, "big")


def t_circuit_accepts_python_merkle_root_only():
    bridge = _bridge_or_skip("circuit_accepts_python_merkle_root_only")
    camera_secrets = [new_camera_secret() for _ in range(3)]
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    binding = binding_digest(MODE_VIDEO, DIGEST, MESSAGE)
    witness = bridge._compute_witness(bridge.circuit_input(camera_secrets[1], registry, binding))
    witness.unlink()
    witness.parent.rmdir()
    forged = bridge.circuit_input(camera_secrets[1], registry, binding)
    forged["secret"] = str(camera_secrets[2])  # another camera's secret on camera 1's path
    try:
        bridge._compute_witness(forged)
    except RuntimeError:
        return
    raise AssertionError("the circuit accepted a secret that does not open the Merkle path")


# ── Groth16 ───────────────────────────────────────────────────────────── #

def t_groth16_proof_binds_root_and_binding():
    bridge = _bridge_or_skip("groth16_proof_binds_root_and_binding")
    camera_secrets = [new_camera_secret() for _ in range(4)]
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    binding = binding_digest(MODE_VIDEO, DIGEST, MESSAGE)
    proof = bridge.prove(camera_secrets[3], registry, binding)
    assert bridge.verify(proof, registry.root, binding), "fresh proof must verify"
    assert bridge.verify(bytes_to_proof(proof_to_bytes(proof)), registry.root, binding), "compressed proof must verify"
    assert not bridge.verify(proof, registry.root, binding_digest(MODE_VIDEO, DIGEST, MESSAGE + b"!")), "other message"
    assert not bridge.verify(proof, registry.root, binding_digest(MODE_VIDEO, bytes(32), MESSAGE)), "other video"
    other = CameraRegistry([camera_public_key(new_camera_secret())])
    assert not bridge.verify(proof, other.root, binding), "other registry"
    assert CameraProofBridge.public_signals(registry.root, binding)[0] == str(registry.root)


def t_unregistered_camera_cannot_prove():
    bridge = _bridge_or_skip("unregistered_camera_cannot_prove")
    registry = CameraRegistry([camera_public_key(new_camera_secret()) for _ in range(2)])
    _expect_value_error(lambda: bridge.prove(new_camera_secret(), registry,
                                             binding_digest(MODE_VIDEO, DIGEST, MESSAGE)), "unregistered camera")


def t_setup_transcript_records_a_verified_ceremony():
    bridge = _bridge_or_skip("setup_transcript_records_a_verified_ceremony")
    transcript_path = bridge.build_dir / "camera_video_setup.json"
    if not transcript_path.is_file():
        SKIP("setup_transcript_records_a_verified_ceremony", "no setup transcript")
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    assert transcript["zkey_verify"] == "ZKey Ok!"
    assert len(transcript["phase2_contributions"]) >= 1 and transcript["beacon"]["hash_hex"]


def main():
    section("ZK camera proof: format, Poseidon, registry, binding, Groth16")
    results = [
        run_test("proof_bytes_roundtrip", t_proof_bytes_roundtrip),
        run_test("bytes_to_proof_rejects_malformed", t_bytes_to_proof_rejects_malformed),
        run_test("snarkjs_verify_fails_closed", t_snarkjs_verify_fails_closed),
        run_test("payload_roundtrip_and_layout", t_payload_roundtrip_and_layout),
        run_test("payload_rejects_other_layouts", t_payload_rejects_other_layouts),
        run_test("poseidon_matches_circomlib_vectors", t_poseidon_matches_circomlib_vectors),
        run_test("registry_paths_rebuild_the_root", t_registry_paths_rebuild_the_root),
        run_test("binding_rules", t_binding_rules),
        run_test("circuit_accepts_python_merkle_root_only", t_circuit_accepts_python_merkle_root_only),
        run_test("groth16_proof_binds_root_and_binding", t_groth16_proof_binds_root_and_binding),
        run_test("unregistered_camera_cannot_prove", t_unregistered_camera_cannot_prove),
        run_test("setup_transcript_records_a_verified_ceremony", t_setup_transcript_records_a_verified_ceremony),
    ]
    sys.exit(summarise(results, "ZK proof"))


if __name__ == '__main__':
    main()
