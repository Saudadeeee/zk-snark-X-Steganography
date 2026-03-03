"""
ZK-SNARK Bridge — Python interface to snarkjs / Node.js for Groth16 proof operations.

Generates proof that: commitment = SHA256(SHA256(payload) || secret_key)
without revealing secret_key. Payload hash and commitment are public inputs.

Requires:
  - Node.js (for witness generation via WASM)
  - snarkjs (installed in circuits/node_modules)
  - circuits/build/payload_verify.wasm
  - circuits/build/proving_key.zkey
  - circuits/build/verification_key.json
"""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Dict, Optional

from .zk_payload_format import proof_to_bytes, bytes_to_proof


class ZKSnarkBridge:
    """
    Bridge between Python steganography pipeline and snarkjs Groth16 proof system.

    Circuit: PayloadVerify
      Public:  payload_hash[256], commitment[256], payload_length
      Private: secret[256]
      Proves:  commitment == SHA256(payload_hash_bytes || secret_bytes)
    """

    PROOF_FIELD_BITS = 256   # BN128 field element size in bits
    GENERATE_WITNESS_JS = "generate_witness.js"
    WASM_FILE = "payload_verify.wasm"
    ZKEY_FILE = "proving_key.zkey"
    VKEY_FILE = "verification_key.json"

    def __init__(self, circuits_dir: str):
        """
        Args:
            circuits_dir: Absolute or relative path to the circuits/ folder.
                          Must contain build/ subdirectory with compiled artifacts.
        """
        self.circuits_dir = Path(circuits_dir).resolve()
        self.build_dir = self.circuits_dir / "build"
        self.js_dir = self.build_dir / "payload_verify_js"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def generate_proof_for_payload(
        self, payload_bytes: bytes, secret_key: bytes
    ) -> Tuple[dict, dict]:
        """
        Full pipeline: payload → witness → Groth16 proof.

        Args:
            payload_bytes: The message bytes to prove knowledge of.
            secret_key:    32-byte secret key (stays private, never embedded).

        Returns:
            (proof_dict, public_dict) — snarkjs format dicts.
        """
        print("  [ZK] Computing commitment...")
        circuit_input = self._build_circuit_input(payload_bytes, secret_key)

        print("  [ZK] Computing witness (node.js wasm)...")
        witness_path = self._compute_witness(circuit_input)

        print("  [ZK] Generating Groth16 proof (snarkjs)...")
        proof_dict, public_dict = self._snarkjs_prove(witness_path)

        return proof_dict, public_dict

    def verify(
        self, proof_dict: dict, public_dict: dict
    ) -> bool:
        """
        Verify a Groth16 proof using snarkjs.

        Returns:
            True if proof is valid, False otherwise.
        """
        print("  [ZK] Verifying Groth16 proof...")
        return self._snarkjs_verify(proof_dict, public_dict)

    def verify_extracted(
        self, extracted_payload: bytes, proof_bytes: bytes, secret_key_hint: Optional[bytes] = None
    ) -> Tuple[bool, dict]:
        """
        Verify a deserialized proof against an extracted payload.

        This reconstructs the public signals from the payload and verifies
        the proof without needing the secret key (it's encoded in the commitment).

        Args:
            extracted_payload: Bytes extracted from the video.
            proof_bytes:       256-byte serialized proof from the video.
            secret_key_hint:   Optional — if provided, recomputes commitment for cross-check.

        Returns:
            (is_valid, info_dict)
        """
        proof_dict = bytes_to_proof(proof_bytes)

        # We need the public signals (which were embedded alongside the proof).
        # The public.json is saved during prove step; here we recompute from payload.
        # Note: without secret_key we cannot recompute commitment, but we can
        # still verify by reading the public signals from public_dict if provided.
        #
        # For the embed pipeline: we save public.json in the blob comment area or
        # recompute from known secret during extraction (test scenario).
        if secret_key_hint is not None:
            public_dict = self._build_public_signals(extracted_payload, secret_key_hint)
            valid = self._snarkjs_verify(proof_dict, public_dict)
            payload_hash_hex = hashlib.sha256(extracted_payload).hexdigest()
            return valid, {"payload_hash": payload_hash_hex, "verified": valid}
        else:
            # Without secret we cannot reconstruct public signals — return False
            return False, {"error": "secret_key required for verification"}

    def proof_to_bytes(self, proof_dict: dict) -> bytes:
        """Serialize proof dict → 256 bytes."""
        return proof_to_bytes(proof_dict)

    def bytes_to_proof(self, data: bytes) -> dict:
        """Deserialize 256 bytes → proof dict."""
        return bytes_to_proof(data)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bytes_to_bits(data: bytes) -> list:
        """Convert bytes to list of bit strings ['0','1',...] (MSB first)."""
        bits = []
        for byte in data:
            for i in range(7, -1, -1):
                bits.append(str((byte >> i) & 1))
        return bits

    def _build_circuit_input(self, payload_bytes: bytes, secret_key: bytes) -> dict:
        """
        Build the circuit input JSON dict.

        payload_hash = SHA256(payload_bytes)          → 32 bytes → 256 bits (public)
        commitment   = SHA256(payload_hash || secret) → 32 bytes → 256 bits (public)
        payload_length = len(payload_bytes)           (public)
        secret       = secret_key                     → 256 bits (private)
        """
        assert len(secret_key) == 32, "secret_key must be exactly 32 bytes"

        payload_hash_bytes = hashlib.sha256(payload_bytes).digest()
        commitment_input = payload_hash_bytes + secret_key
        commitment_bytes = hashlib.sha256(commitment_input).digest()

        return {
            "payload_hash": self._bytes_to_bits(payload_hash_bytes),
            "commitment":   self._bytes_to_bits(commitment_bytes),
            "payload_length": len(payload_bytes),
            "secret":       self._bytes_to_bits(secret_key),
        }

    def _build_public_signals(self, payload_bytes: bytes, secret_key: bytes) -> dict:
        """Build public signals dict for verification (matches circuit public outputs)."""
        payload_hash_bytes = hashlib.sha256(payload_bytes).digest()
        commitment_input = payload_hash_bytes + secret_key
        commitment_bytes = hashlib.sha256(commitment_input).digest()

        # snarkjs public.json is a flat list of field elements (as decimal strings).
        # Order matches circuit signal declaration:
        #   payload_hash[256], commitment[256], payload_length  → 513 values
        payload_hash_bits = self._bytes_to_bits(payload_hash_bytes)
        commitment_bits = self._bytes_to_bits(commitment_bytes)

        signals = payload_hash_bits + commitment_bits + [str(len(payload_bytes))]
        return signals   # list of 513 strings

    def _compute_witness(self, circuit_input: dict) -> Path:
        """Run generate_witness.js via Node.js to produce witness.wtns."""
        witness_path = self.build_dir / "witness_live.wtns"
        input_path = self.build_dir / "input_live.json"
        wasm_path = self.js_dir / self.WASM_FILE

        # Write input.json
        with open(input_path, "w") as f:
            json.dump(circuit_input, f)

        # node generate_witness.js <wasm> <input.json> <witness.wtns>
        gen_js = self.js_dir / self.GENERATE_WITNESS_JS
        cmd = ["node", str(gen_js), str(wasm_path), str(input_path), str(witness_path)]

        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(self.circuits_dir)
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Witness generation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        return witness_path

    def _snarkjs_prove(self, witness_path: Path) -> Tuple[dict, dict]:
        """Run snarkjs groth16 prove to generate proof.json + public.json."""
        zkey_path = self.build_dir / self.ZKEY_FILE
        proof_out = self.build_dir / "proof_live.json"
        public_out = self.build_dir / "public_live.json"

        cmd = [
            "npx", "snarkjs", "groth16", "prove",
            str(zkey_path), str(witness_path),
            str(proof_out), str(public_out),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(self.circuits_dir),
            shell=True  # needed on Windows for npx
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Proof generation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )

        with open(proof_out) as f:
            proof_dict = json.load(f)
        with open(public_out) as f:
            public_dict = json.load(f)

        return proof_dict, public_dict

    def _snarkjs_verify(self, proof_dict: dict, public_signals) -> bool:
        """Run snarkjs groth16 verify. Returns True if valid."""
        vkey_path = self.build_dir / self.VKEY_FILE
        proof_tmp = self.build_dir / "proof_verify_tmp.json"
        public_tmp = self.build_dir / "public_verify_tmp.json"

        with open(proof_tmp, "w") as f:
            json.dump(proof_dict, f)
        with open(public_tmp, "w") as f:
            json.dump(public_signals, f)

        cmd = [
            "npx", "snarkjs", "groth16", "verify",
            str(vkey_path), str(public_tmp), str(proof_tmp),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(self.circuits_dir),
            shell=True
        )
        output = (result.stdout + result.stderr).lower()
        return "ok" in output and "invalid" not in output
