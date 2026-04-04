"""
verifier.py — Public API: Extract and verify a ZK proof from a stego video.

Quick start:
    from src.verifier import verify, VerifyResult

    result = verify(
        stego_video_path    = "data/output/stego.h264",
        original_video_path = "data/encoded/foreman_cif_g8.h264",
        circuits_dir        = "circuits/",
        secret_key          = secret_key,
        message_length      = len(original_message),
    )
    if result.valid:
        print(f"Proof valid! Message: {result.message}")
    else:
        print("Proof invalid or extraction failed.")
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

from .core.pipeline        import extract_all_idr_blocks, extract_bits_direct
from .core.stego           import CAVLCSafetyFilter
from .bitstream.bitstream_ops import BitstreamReconstructor
from .zk_proof             import ZKSnarkBridge, unpack, blob_bit_length


@dataclass
class VerifyResult:
    """Result returned by verify()."""
    valid:          bool            # True if ZK proof verifies successfully
    message:        Optional[bytes] # Extracted message (None if invalid)
    proof_dict:     Optional[dict]  # Raw proof dict (None if unpack failed)
    public_dict:    Optional[list]  # Public signals (None if unpack failed)
    bits_extracted: int             # Number of bits extracted from stego video


def verify(
    stego_video_path:    str,
    original_video_path: str,
    circuits_dir:        str,
    secret_key:          bytes,
    message_length:      int,
    max_modifications_per_block: int = 1,
) -> VerifyResult:
    """
    Extract and verify the ZK proof embedded in a stego H.264 video.

    Pipeline:
        1. Parse original video  — reconstruct embedding position map
        2. Get safe positions    — same order as used during embed
        3. Extract bits          — read T1 signs from stego video
        4. Unpack blob           — split into (message, proof_bytes)
        5. Verify ZK proof       — snarkjs groth16 verify

    Args:
        stego_video_path:    Path to the stego H.264 video.
        original_video_path: Path to the original (pre-embed) H.264 video.
        circuits_dir:        Path to circuits/ directory (ZK build artifacts).
        secret_key:          32-byte secret key used during embedding.
        message_length:      Expected message length in bytes.
        max_modifications_per_block: Must match value used in embed() (default 1).

    Returns:
        VerifyResult with valid flag, message, and proof details.

    Raises:
        FileNotFoundError: If stego_video_path, original_video_path, or circuits_dir does not exist.
        ValueError: If secret_key is not 32 bytes or message_length is not positive.
    """
    # --- Input validation ---
    if not os.path.isfile(stego_video_path):
        raise FileNotFoundError(f"Stego video not found: {stego_video_path}")
    if not os.path.isfile(original_video_path):
        raise FileNotFoundError(f"Original video not found: {original_video_path}")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    if message_length <= 0:
        raise ValueError("message_length must be a positive integer")

    # 1. Parse original video — get embedding position map
    rec = BitstreamReconstructor()
    coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map = \
        extract_all_idr_blocks(original_video_path, rec)

    # 2. Get safe positions (same descending order as embedding)
    safety = CAVLCSafetyFilter()
    safe_positions = safety.get_safe_positions(
        coefficients,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
    )

    # 3. Extract bits from stego video
    payload_bits   = blob_bit_length(b'\x00' * message_length)
    extracted_blob = extract_bits_direct(
        stego_video_path,
        safe_positions,
        frame_verified_data,
        nC_map,
        payload_bits,
        max_modifications_per_block=max_modifications_per_block,
    )

    # 4. Unpack blob → (message, proof_bytes)
    try:
        message, proof_bytes = unpack(extracted_blob)
    except ValueError:
        return VerifyResult(
            valid=False, message=None, proof_dict=None,
            public_dict=None, bits_extracted=len(extracted_blob) * 8,
        )

    # 5. Verify ZK proof
    bridge         = ZKSnarkBridge(circuits_dir)
    proof_dict     = bridge.bytes_to_proof(proof_bytes)
    public_signals = bridge._build_public_signals(message, secret_key)
    is_valid       = bridge.verify(proof_dict, public_signals)

    return VerifyResult(
        valid=is_valid,
        message=message if is_valid else None,
        proof_dict=proof_dict,
        public_dict=public_signals,
        bits_extracted=payload_bits,
    )
