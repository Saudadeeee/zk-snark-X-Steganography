"""
ZK Payload Format — Binary packing of (message, proof) into a single blob.

Blob layout:
  [4 bytes big-endian: len(message)]
  [len(message) bytes: message]
  [PROOF_SIZE_BYTES bytes: Groth16 proof binary]

Groth16 BN128 proof binary layout (256 bytes total):
  [32 bytes: pi_a.x]
  [32 bytes: pi_a.y]
  [32 bytes: pi_b.x[0]]
  [32 bytes: pi_b.x[1]]
  [32 bytes: pi_b.y[0]]
  [32 bytes: pi_b.y[1]]
  [32 bytes: pi_c.x]
  [32 bytes: pi_c.y]
"""

import struct
from typing import Tuple

# Groth16 BN128: 8 field elements × 32 bytes = 256 bytes
PROOF_SIZE_BYTES = 256


def proof_to_bytes(proof_dict: dict) -> bytes:
    """
    Serialize a snarkjs Groth16 proof dict into 256-byte binary.

    proof_dict format (from snarkjs groth16 prove):
        {
          "pi_a": ["<int_str>", "<int_str>", "1"],
          "pi_b": [["<int_str>", "<int_str>"], ["<int_str>", "<int_str>"], ["1", "0"]],
          "pi_c": ["<int_str>", "<int_str>", "1"],
          "protocol": "groth16",
          "curve": "bn128"
        }
    """
    def _to32(val_str: str) -> bytes:
        return int(val_str).to_bytes(32, "big")

    pi_a = proof_dict["pi_a"]
    pi_b = proof_dict["pi_b"]
    pi_c = proof_dict["pi_c"]

    blob = b"".join([
        _to32(pi_a[0]),       # pi_a.x
        _to32(pi_a[1]),       # pi_a.y
        _to32(pi_b[0][0]),    # pi_b.x[0]
        _to32(pi_b[0][1]),    # pi_b.x[1]
        _to32(pi_b[1][0]),    # pi_b.y[0]
        _to32(pi_b[1][1]),    # pi_b.y[1]
        _to32(pi_c[0]),       # pi_c.x
        _to32(pi_c[1]),       # pi_c.y
    ])
    assert len(blob) == PROOF_SIZE_BYTES, f"Expected {PROOF_SIZE_BYTES} bytes, got {len(blob)}"
    return blob


def bytes_to_proof(data: bytes) -> dict:
    """
    Deserialize 256-byte binary back to snarkjs Groth16 proof dict.
    """
    assert len(data) == PROOF_SIZE_BYTES, f"Expected {PROOF_SIZE_BYTES} bytes, got {len(data)}"

    def _from32(chunk: bytes) -> str:
        return str(int.from_bytes(chunk, "big"))

    parts = [data[i*32:(i+1)*32] for i in range(8)]

    return {
        "pi_a": [_from32(parts[0]), _from32(parts[1]), "1"],
        "pi_b": [
            [_from32(parts[2]), _from32(parts[3])],
            [_from32(parts[4]), _from32(parts[5])],
            ["1", "0"],
        ],
        "pi_c": [_from32(parts[6]), _from32(parts[7]), "1"],
        "protocol": "groth16",
        "curve": "bn128",
    }


def pack(message_bytes: bytes, proof_bytes: bytes) -> bytes:
    """
    Pack message + proof into a single blob:
      [4 bytes: len(message)][message][proof (256 bytes)]
    """
    assert len(proof_bytes) == PROOF_SIZE_BYTES, \
        f"Proof must be exactly {PROOF_SIZE_BYTES} bytes, got {len(proof_bytes)}"
    header = struct.pack(">I", len(message_bytes))   # 4 bytes big-endian
    return header + message_bytes + proof_bytes


def unpack(blob: bytes) -> Tuple[bytes, bytes]:
    """
    Unpack blob into (message_bytes, proof_bytes).
    Raises ValueError on malformed data.
    """
    if len(blob) < 4:
        raise ValueError(f"Blob too short to contain header: {len(blob)} bytes")

    msg_len = struct.unpack(">I", blob[:4])[0]
    expected_total = 4 + msg_len + PROOF_SIZE_BYTES

    if len(blob) < expected_total:
        raise ValueError(
            f"Blob too short: expected {expected_total} bytes, got {len(blob)}"
        )

    message_bytes = blob[4: 4 + msg_len]
    proof_bytes = blob[4 + msg_len: 4 + msg_len + PROOF_SIZE_BYTES]
    return message_bytes, proof_bytes


def blob_bit_length(message_bytes: bytes) -> int:
    """Return total blob length in bits given a message."""
    return (4 + len(message_bytes) + PROOF_SIZE_BYTES) * 8
