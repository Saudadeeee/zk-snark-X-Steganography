"""
zk_proof.py — camera-proof payload format and Groth16 bridge.

Statement (``circuits/camera_video.circom``): "a camera registered under
``root`` vouches for this binding", where the binding commits to the video
digest and the message (``src/video_binding.py``). The verifier needs only the
registry root and the verification key, never the camera secret, and learns
nothing about which registered camera produced the proof.

Public API:
    # Proof binary form (BN254, 129-byte point compression)
    PROOF_SIZE_BYTES, proof_to_bytes(proof_dict), bytes_to_proof(data)

    # Payload carried in the stego channel
    pack_payload(mode, message, proof_bytes)   -> bytes
    unpack_payload(blob)                       -> CameraPayload
    payload_size(message_bytes)                -> int

    # Groth16 (snarkjs)
    CameraProofBridge(circuits_dir)
        .prove(secret, registry, camera_index, binding) -> proof_dict
        .verify(proof_dict, root, binding)              -> bool
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from src.camera_registry import CameraRegistry, camera_public_key
from src.video_binding import MODE_MESSAGE_ONLY, MODE_VIDEO, binding_public_inputs

logger = logging.getLogger(__name__)

# On Windows, npx/npm are .cmd scripts that require shell=True. The locally
# installed snarkjs CLI is preferred so the fallback is only used when
# circuits/node_modules is absent.
_NPX_SHELL = sys.platform == "win32"
_SNARKJS_LOCAL_CLI = Path("node_modules") / "snarkjs" / "build" / "cli.cjs"
_SUBPROCESS_TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}


# =============================================================================
# Binary proof format
# =============================================================================

# Groth16 BN128 point compression: 4 x-coordinates x 32 bytes + 1 byte of y signs.
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
    if len(blob) != PROOF_SIZE_BYTES:
        raise ValueError(f"Serialized proof must be {PROOF_SIZE_BYTES} bytes, got {len(blob)}")
    return blob


def _field_element(x_bytes: bytes) -> int:
    value = int.from_bytes(x_bytes, "big")
    if value >= _P:
        raise ValueError("Proof coordinate is not a canonical BN254 field element")
    return value


def bytes_to_proof(data: bytes) -> dict:
    """Deserialize 129-byte binary → snarkjs Groth16 proof dict via Decompression.

    Raises ValueError for malformed input (wrong size, unknown flag bits,
    non-canonical coordinates, or points not on the curve).
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) != PROOF_SIZE_BYTES:
        raise ValueError(f"Serialized proof must be {PROOF_SIZE_BYTES} bytes")

    parts = [bytes(data[i * 32:(i + 1) * 32]) for i in range(4)]
    flags = data[128]
    if flags & ~0b111:
        raise ValueError("Serialized proof has unknown flag bits set")
    y_a_sign = (flags >> 2) & 1
    y_b_sign = (flags >> 1) & 1
    y_c_sign = flags & 1

    def recover_g1(x_bytes, sign):
        x = _field_element(x_bytes)
        rhs = (pow(x, 3, _P) + 3) % _P
        y = pow(rhs, (_P + 1) // 4, _P)
        if (y * y) % _P != rhs:
            raise ValueError("Proof G1 x-coordinate is not on the curve")
        if (y & 1) != sign:
            y = _P - y
        return str(x), str(y)

    x_a, y_a = recover_g1(parts[0], y_a_sign)
    x_c, y_c = recover_g1(parts[3], y_c_sign)

    inv82 = pow(82, _P - 2, _P)
    b0, b1 = (27 * inv82) % _P, (-3 * inv82) % _P
    x0, x1 = _field_element(parts[1]), _field_element(parts[2])

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
    if _fq2_mul((c, d), (c, d)) != (A, B):
        raise ValueError("Proof G2 x-coordinate is not on the twist curve")

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


# =============================================================================
# Payload carried in the stego channel
# =============================================================================

PAYLOAD_FORMAT = 0x01
PAYLOAD_HEADER_BYTES = 4  # format, binding mode, message length (BE16)
MAX_MESSAGE_BYTES = 0xFFFF


@dataclass(frozen=True)
class CameraPayload:
    mode: int
    message: bytes
    proof_bytes: bytes


def payload_size(message_bytes: int) -> int:
    return PAYLOAD_HEADER_BYTES + message_bytes + PROOF_SIZE_BYTES


def pack_payload(mode: int, message: bytes, proof_bytes: bytes) -> bytes:
    """``[format 0x01][mode][message_len BE16][message][proof 129 B]``."""
    if mode not in (MODE_VIDEO, MODE_MESSAGE_ONLY):
        raise ValueError("binding mode must be 0 (video) or 1 (message only)")
    if len(message) > MAX_MESSAGE_BYTES:
        raise ValueError("message exceeds 65535 bytes")
    if len(proof_bytes) != PROOF_SIZE_BYTES:
        raise ValueError(f"proof_bytes must be {PROOF_SIZE_BYTES} bytes, got {len(proof_bytes)}")
    return bytes((PAYLOAD_FORMAT, mode)) + len(message).to_bytes(2, "big") + message + proof_bytes


def unpack_payload(blob: bytes) -> CameraPayload:
    """Strict inverse of :func:`pack_payload`; raises ValueError on any other layout."""
    if len(blob) < PAYLOAD_HEADER_BYTES or blob[0] != PAYLOAD_FORMAT:
        raise ValueError("payload format is not a camera proof payload")
    if blob[1] not in (MODE_VIDEO, MODE_MESSAGE_ONLY):
        raise ValueError("payload binding mode is invalid")
    message_length = int.from_bytes(blob[2:4], "big")
    if len(blob) != payload_size(message_length):
        raise ValueError("payload length does not match its message length")
    message = blob[PAYLOAD_HEADER_BYTES:PAYLOAD_HEADER_BYTES + message_length]
    return CameraPayload(blob[1], message, blob[PAYLOAD_HEADER_BYTES + message_length:])


# =============================================================================
# Groth16 bridge (snarkjs)
# =============================================================================


class CameraProofBridge:
    """Groth16 prove/verify for ``camera_video.circom`` through snarkjs."""

    CIRCUIT = "camera_video"
    GENERATE_WITNESS_JS = "generate_witness.js"

    def __init__(self, circuits_dir: str | Path):
        self.circuits_dir = Path(circuits_dir).resolve()
        self.build_dir = self.circuits_dir / "build"
        self.js_dir = self.build_dir / f"{self.CIRCUIT}_js"
        self.wasm_path = self.js_dir / f"{self.CIRCUIT}.wasm"
        self.zkey_path = self.build_dir / f"{self.CIRCUIT}.zkey"
        self.vkey_path = self.build_dir / f"{self.CIRCUIT}_vkey.json"
        self._remove_stale_temp_dirs()

    def required_files(self) -> list[Path]:
        return [self.wasm_path, self.js_dir / self.GENERATE_WITNESS_JS, self.zkey_path, self.vkey_path,
                self.circuits_dir / _SNARKJS_LOCAL_CLI]

    def _remove_stale_temp_dirs(self, max_age_seconds: float = 3600.0) -> None:
        """Delete witness/verify temp dirs left by a killed process.

        Normal runs clean up in ``finally``; a hard kill between witness and
        proof generation leaves a witness file that encodes the camera secret.
        Only directories older than ``max_age_seconds`` are removed so a
        concurrent prover's live directory is never touched.
        """
        if not self.build_dir.is_dir():
            return
        cutoff = time.time() - max_age_seconds
        for pattern in ("zkp_witness_*", "zkp_verify_*"):
            for path in self.build_dir.glob(pattern):
                try:
                    if path.is_dir() and path.stat().st_mtime < cutoff:
                        shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    continue

    @staticmethod
    def public_signals(root: int, binding: bytes) -> list[str]:
        """Public input order of camera_video.circom: [root, bindingHi, bindingLo]."""
        high, low = binding_public_inputs(binding)
        return [str(root), str(high), str(low)]

    def circuit_input(self, secret: int, registry: CameraRegistry, binding: bytes) -> dict:
        index = registry.index_of(camera_public_key(secret))
        path = registry.path(index)
        high, low = binding_public_inputs(binding)
        return {"secret": str(secret), "siblings": [str(v) for v in path.siblings],
                "pathIndices": [str(v) for v in path.path_indices], "root": str(registry.root),
                "bindingHi": str(high), "bindingLo": str(low)}

    def prove(self, secret: int, registry: CameraRegistry, binding: bytes) -> dict:
        """Groth16 proof that a camera of ``registry`` vouches for ``binding``."""
        self._check_node_available()
        circuit_input = self.circuit_input(secret, registry, binding)
        witness_path = self._compute_witness(circuit_input)
        proof, public = self._snarkjs_prove(witness_path)
        if public != self.public_signals(registry.root, binding):
            raise RuntimeError("snarkjs returned unexpected public signals")
        return proof

    def verify(self, proof_dict: dict, root: int, binding: bytes) -> bool:
        """True only if snarkjs accepts the proof for this registry root and binding."""
        self._check_node_available()
        return self._snarkjs_verify(proof_dict, self.public_signals(root, binding))

    def _compute_witness(self, circuit_input: dict) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="zkp_witness_", dir=str(self.build_dir)))
        witness_path = temp_dir / "witness.wtns"
        input_path = temp_dir / "input.json"
        try:
            input_path.write_text(json.dumps(circuit_input), encoding="utf-8")
            result = subprocess.run(
                ["node", str(self.js_dir / self.GENERATE_WITNESS_JS), str(self.wasm_path), str(input_path),
                 str(witness_path)],
                capture_output=True, cwd=str(self.circuits_dir), **_SUBPROCESS_TEXT,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Witness generation failed:\n{result.stdout}\n{result.stderr}")
            return witness_path
        except BaseException:
            # A failed witness can leave private intermediate data behind.
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        finally:
            # The input file holds the camera secret in plaintext.
            input_path.unlink(missing_ok=True)

    def _snarkjs_prove(self, witness_path: Path) -> tuple[dict, list]:
        temp_dir = witness_path.parent
        proof_out, public_out = temp_dir / "proof.json", temp_dir / "public.json"
        try:
            result = self._run_snarkjs(
                ["groth16", "prove", str(self.zkey_path), str(witness_path), str(proof_out), str(public_out)])
            if result.returncode != 0:
                raise RuntimeError(f"Proof generation failed:\n{result.stdout}\n{result.stderr}")
            return (json.loads(proof_out.read_text(encoding="utf-8")),
                    json.loads(public_out.read_text(encoding="utf-8")))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _snarkjs_verify(self, proof_dict: dict, public_signals: list) -> bool:
        temp_dir = Path(tempfile.mkdtemp(prefix="zkp_verify_", dir=str(self.build_dir)))
        proof_tmp, public_tmp = temp_dir / "proof.json", temp_dir / "public.json"
        try:
            proof_tmp.write_text(json.dumps(proof_dict), encoding="utf-8")
            public_tmp.write_text(json.dumps(public_signals), encoding="utf-8")
            result = self._run_snarkjs(["groth16", "verify", str(self.vkey_path), str(public_tmp), str(proof_tmp)])
            # snarkjs exits 0 only for a valid proof and logs "OK!". Require both
            # so a crash, missing file, or unexpected output never verifies.
            stdout_lines = [line.strip() for line in (result.stdout or "").splitlines()]
            reported_ok = any(line.endswith("OK!") for line in stdout_lines)
            if result.returncode == 0 and reported_ok:
                return True
            if result.returncode == 0:
                logger.error("[ZK] snarkjs exited 0 without reporting OK!; treating proof as invalid")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_snarkjs(self, args: list) -> subprocess.CompletedProcess:
        """Run snarkjs, preferring the locally installed CLI without a shell."""
        local_cli = self.circuits_dir / _SNARKJS_LOCAL_CLI
        if local_cli.is_file():
            command, use_shell = ["node", str(local_cli), *args], False
        else:
            command, use_shell = ["npx", "snarkjs", *args], _NPX_SHELL
        return subprocess.run(command, capture_output=True, cwd=str(self.circuits_dir), shell=use_shell,
                              **_SUBPROCESS_TEXT)

    @staticmethod
    def _check_node_available() -> None:
        """Raise RuntimeError with actionable message if node is not on PATH."""
        if shutil.which("node") is None:
            raise RuntimeError(
                "Node.js is required but 'node' was not found on PATH.\n"
                "Install from https://nodejs.org/ and ensure it is on PATH."
            )
