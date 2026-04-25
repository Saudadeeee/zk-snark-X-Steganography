"""
zk_proof.py — ZK-SNARK proof generation, verification and binary format.

Combines:
  - Groth16 proof binary serialization (BN128, 256 bytes)
  - Payload blob packing: [4B length][message][256B proof]
  - Python bridge to snarkjs / Node.js for proof generation and verification

Public API:
    # Binary format
    PROOF_SIZE_BYTES          — 256
    proof_to_bytes(proof_dict)  → bytes
    bytes_to_proof(data)        → dict
    pack(message, proof_bytes)  → bytes
    unpack(blob)                → (message, proof_bytes)
    blob_bit_length(message)    → int

    # ZK operations
    ZKSnarkBridge(circuits_dir)
        .generate_proof_for_payload(payload, secret_key) → (proof_dict, public_dict)
        .verify(proof_dict, public_dict)                 → bool
        .proof_to_bytes(proof_dict)                      → bytes
        .bytes_to_proof(data)                            → dict

Requires:
    Node.js + snarkjs in circuits/node_modules
    circuits/build/payload_verify.wasm
    circuits/build/proving_key.zkey
    circuits/build/verification_key.json
"""

import hashlib
import json
import logging
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

# On Windows, npx/npm are .cmd scripts that require shell=True.
# On Unix we keep shell=False for security.
_SHELL = sys.platform == "win32"


# =============================================================================
# Binary format  (formerly zk_payload_format.py)
# =============================================================================

# Groth16 BN128 Point Compression
# 4 field elements (X coords) × 32 bytes + 1 byte for 3 signs = 129 bytes
PROOF_SIZE_BYTES = 129

_P = 21888242871839275222246405745257275088696311157297823662689037894645226208583

def _fq2_add(a, b): return (a[0]+b[0])%_P, (a[1]+b[1])%_P
def _fq2_mul(a, b): return (a[0]*b[0] - a[1]*b[1])%_P, (a[0]*b[1] + a[1]*b[0])%_P


def proof_to_bytes(proof_dict: dict) -> bytes:
    """
    Serialize a snarkjs Groth16 proof dict → 129-byte point compressed binary.
    """
    def _to32(val_str: str) -> bytes:
        return int(val_str).to_bytes(32, "big")

    pi_a = proof_dict["pi_a"]
    pi_b = proof_dict["pi_b"]
    pi_c = proof_dict["pi_c"]

    # Signs for Y coordinates (0 if even, 1 if odd)
    y_a_sign = int(pi_a[1]) & 1
    y_b0, y_b1 = int(pi_b[1][0]), int(pi_b[1][1])
    y_b_sign = (y_b0 & 1) if y_b0 != 0 else (y_b1 & 1)
    y_c_sign = int(pi_c[1]) & 1

    flags = (y_a_sign << 2) | (y_b_sign << 1) | y_c_sign

    blob = b"".join([
        _to32(pi_a[0]),     # pi_a.x
        _to32(pi_b[0][0]),  # pi_b.x[0]
        _to32(pi_b[0][1]),  # pi_b.x[1]
        _to32(pi_c[0]),     # pi_c.x
        flags.to_bytes(1, "big")
    ])
    assert len(blob) == PROOF_SIZE_BYTES
    return blob


def bytes_to_proof(data: bytes) -> dict:
    """Deserialize 129-byte binary → snarkjs Groth16 proof dict via Decompression."""
    assert len(data) == PROOF_SIZE_BYTES

    parts = [data[i * 32:(i + 1) * 32] for i in range(4)]
    flags = int.from_bytes(data[128:129], "big")
    y_a_sign = (flags >> 2) & 1
    y_b_sign = (flags >> 1) & 1
    y_c_sign = flags & 1

    def recover_g1(x_bytes, sign):
        x = int.from_bytes(x_bytes, "big")
        y = pow((pow(x, 3, _P) + 3) % _P, (_P + 1) // 4, _P)
        if (y & 1) != sign:
            y = _P - y
        return str(x), str(y)

    x_a, y_a = recover_g1(parts[0], y_a_sign)
    x_c, y_c = recover_g1(parts[3], y_c_sign)

    inv82 = pow(82, _P - 2, _P)
    b0, b1 = (27 * inv82) % _P, (-3 * inv82) % _P
    x0, x1 = int.from_bytes(parts[1], "big"), int.from_bytes(parts[2], "big")
    
    X2 = _fq2_mul((x0, x1), (x0, x1))
    X3 = _fq2_mul(X2, (x0, x1))
    A, B = _fq2_add(X3, (b0, b1))

    R = pow((A*A + B*B) % _P, (_P + 1) // 4, _P)
    inv2 = pow(2, _P - 2, _P)
    
    cand_c2 = ((R + A) * inv2) % _P
    c = pow(cand_c2, (_P + 1) // 4, _P)
    if pow(c, 2, _P) != cand_c2:
        R = _P - R
        cand_c2 = ((R + A) * inv2) % _P
        c = pow(cand_c2, (_P + 1) // 4, _P)

    cand_d2 = ((R - A) * inv2) % _P
    d = pow(cand_d2, (_P + 1) // 4, _P)

    if (2 * c * d) % _P != B:
        d = _P - d

    my_sign = (c & 1) if c != 0 else (d & 1)
    if my_sign != y_b_sign:
        c, d = (_P - c) % _P, (_P - d) % _P

    return {
        "pi_a": [x_a, y_a, "1"],
        "pi_b": [
            [str(x0), str(x1)],
            [str(c), str(d)],
            ["1", "0"],
        ],
        "pi_c": [x_c, y_c, "1"],
        "protocol": "groth16",
        "curve": "bn128",
    }


def pack(message_bytes: bytes, proof_bytes: bytes) -> bytes:
    """
    Pack message + proof → single blob:
      [4 bytes big-endian: len(message)][message][proof (129 bytes)]
    """
    assert len(proof_bytes) == PROOF_SIZE_BYTES
    return struct.pack(">I", len(message_bytes)) + message_bytes + proof_bytes


def unpack(blob: bytes) -> Tuple[bytes, bytes]:
    """Unpack blob → (message_bytes, proof_bytes). Raises ValueError on bad data."""
    if len(blob) < 4:
        raise ValueError(f"Blob too short: {len(blob)} bytes")
    msg_len = struct.unpack(">I", blob[:4])[0]
    expected = 4 + msg_len + PROOF_SIZE_BYTES
    if len(blob) < expected:
        raise ValueError(f"Blob too short: expected {expected}, got {len(blob)}")
    return blob[4: 4 + msg_len], blob[4 + msg_len: 4 + msg_len + PROOF_SIZE_BYTES]


def blob_bit_length(message_bytes: bytes) -> int:
    """Return total blob length in bits for a given message."""
    return (4 + len(message_bytes) + PROOF_SIZE_BYTES) * 8


# =============================================================================
# ZK bridge  (formerly zk_snark_bridge.py)
# =============================================================================


class ZKSnarkBridge:
    """
    Bridge between Python steganography pipeline and snarkjs Groth16.

    Circuit: PayloadVerify
      Public:  payload_hash[256], commitment[256], payload_length
      Private: secret[256]
      Proves:  commitment == SHA256(payload_hash_bytes || secret_bytes)
    """

    GENERATE_WITNESS_JS = "generate_witness.js"
    WASM_FILE  = "payload_verify.wasm"
    ZKEY_FILE  = "proving_key.zkey"
    VKEY_FILE  = "verification_key.json"

    def __init__(self, circuits_dir: str):
        self.circuits_dir = Path(circuits_dir).resolve()
        self.build_dir    = self.circuits_dir / "build"
        self.js_dir       = self.build_dir / "payload_verify_js"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate_proof_for_payload(
        self, payload_bytes: bytes, secret_key: bytes
    ) -> Tuple[dict, dict]:
        """
        Full pipeline: payload → witness → Groth16 proof.

        Returns:
            (proof_dict, public_dict) — snarkjs format dicts.
        """
        self._check_node_available()
        logger.info("[ZK] Computing commitment...")
        circuit_input = self._build_circuit_input(payload_bytes, secret_key)
        logger.info("[ZK] Computing witness (node.js wasm)...")
        witness_path = self._compute_witness(circuit_input)
        logger.info("[ZK] Generating Groth16 proof (snarkjs)...")
        return self._snarkjs_prove(witness_path)

    def verify(self, proof_dict: dict, public_dict: dict) -> bool:
        """Verify a Groth16 proof using snarkjs. Returns True if valid."""
        self._check_node_available()
        logger.info("[ZK] Verifying Groth16 proof...")
        return self._snarkjs_verify(proof_dict, public_dict)

    def proof_to_bytes(self, proof_dict: dict) -> bytes:
        """Serialize proof dict → 256 bytes."""
        return proof_to_bytes(proof_dict)

    def bytes_to_proof(self, data: bytes) -> dict:
        """Deserialize 256 bytes → proof dict."""
        return bytes_to_proof(data)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bytes_to_bits(data: bytes) -> list:
        """Convert bytes → list of bit strings ['0','1',...] (MSB first)."""
        bits = []
        for byte in data:
            for i in range(7, -1, -1):
                bits.append(str((byte >> i) & 1))
        return bits

    def _build_circuit_input(self, payload_bytes: bytes, secret_key: bytes) -> dict:
        assert len(secret_key) == 32, "secret_key must be exactly 32 bytes"
        payload_hash_bytes = hashlib.sha256(payload_bytes).digest()
        commitment_bytes   = hashlib.sha256(payload_hash_bytes + secret_key).digest()
        return {
            "payload_hash":   self._bytes_to_bits(payload_hash_bytes),
            "commitment":     self._bytes_to_bits(commitment_bytes),
            "payload_length": len(payload_bytes),
            "secret":         self._bytes_to_bits(secret_key),
        }

    def _build_public_signals(self, payload_bytes: bytes, secret_key: bytes) -> list:
        payload_hash_bytes = hashlib.sha256(payload_bytes).digest()
        commitment_bytes   = hashlib.sha256(payload_hash_bytes + secret_key).digest()
        return (self._bytes_to_bits(payload_hash_bytes) +
                self._bytes_to_bits(commitment_bytes) +
                [str(len(payload_bytes))])

    def _compute_witness(self, circuit_input: dict) -> Path:
        witness_path = self.build_dir / "witness_live.wtns"
        input_path   = self.build_dir / "input_live.json"
        wasm_path    = self.js_dir / self.WASM_FILE
        gen_js       = self.js_dir / self.GENERATE_WITNESS_JS

        try:
            with open(input_path, "w") as f:
                json.dump(circuit_input, f)

            result = subprocess.run(
                ["node", str(gen_js), str(wasm_path), str(input_path), str(witness_path)],
                capture_output=True, text=True, cwd=str(self.circuits_dir),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Witness generation failed:\n{result.stdout}\n{result.stderr}"
                )
            return witness_path
        finally:
            # Always delete input file — it contains secret_key in plaintext bits
            input_path.unlink(missing_ok=True)

    def _snarkjs_prove(self, witness_path: Path) -> Tuple[dict, dict]:
        zkey_path  = self.build_dir / self.ZKEY_FILE
        proof_out  = self.build_dir / "proof_live.json"
        public_out = self.build_dir / "public_live.json"

        try:
            result = subprocess.run(
                ["npx", "snarkjs", "groth16", "prove",
                 str(zkey_path), str(witness_path), str(proof_out), str(public_out)],
                capture_output=True, text=True, cwd=str(self.circuits_dir), shell=_SHELL,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Proof generation failed:\n{result.stdout}\n{result.stderr}"
                )
            with open(proof_out) as f:
                proof_dict = json.load(f)
            with open(public_out) as f:
                public_dict = json.load(f)
            return proof_dict, public_dict
        finally:
            witness_path.unlink(missing_ok=True)
            proof_out.unlink(missing_ok=True)
            public_out.unlink(missing_ok=True)

    def _snarkjs_verify(self, proof_dict: dict, public_signals) -> bool:
        vkey_path   = self.build_dir / self.VKEY_FILE
        proof_tmp   = self.build_dir / "proof_verify_tmp.json"
        public_tmp  = self.build_dir / "public_verify_tmp.json"

        try:
            with open(proof_tmp, "w") as f:
                json.dump(proof_dict, f)
            with open(public_tmp, "w") as f:
                json.dump(public_signals, f)

            result = subprocess.run(
                ["npx", "snarkjs", "groth16", "verify",
                 str(vkey_path), str(public_tmp), str(proof_tmp)],
                capture_output=True, text=True, cwd=str(self.circuits_dir), shell=_SHELL,
            )
            output = (result.stdout + result.stderr).lower()
            return "ok" in output and "invalid" not in output
        finally:
            proof_tmp.unlink(missing_ok=True)
            public_tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Dependency checks
    # ------------------------------------------------------------------ #

    @staticmethod
    def _check_node_available() -> None:
        """Raise RuntimeError with actionable message if node is not on PATH."""
        if shutil.which("node") is None:
            raise RuntimeError(
                "Node.js is required but 'node' was not found on PATH.\n"
                "Install from https://nodejs.org/ and ensure it is on PATH."
            )
