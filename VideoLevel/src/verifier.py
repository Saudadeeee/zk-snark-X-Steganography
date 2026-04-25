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
import math
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

from .core.pipeline        import extract_all_idr_blocks, extract_bits_direct
from .core.stego           import CAVLCSafetyFilter
from .core.chaos           import ChaosTransformer
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
    chaos_key: Optional[bytes] = None,
) -> VerifyResult:
    """
    Extract and verify the ZK proof embedded in a stego H.264 video.

    Pipeline:
        1. Parse original video  — reconstruct embedding position map
        2. Get safe positions    — same order as used during embed
       2b. [Chaos] Logistic Map shuffle positions (if chaos_key)
        3. Extract bits          — read T1 signs from stego video
       3b. [Chaos] Arnold Cat Map unscramble payload bits (if chaos_key)
        4. Unpack blob           — split into (message, proof_bytes)
        5. Verify ZK proof       — snarkjs groth16 verify

    Args:
        stego_video_path:    Path to the stego H.264 video.
        original_video_path: Path to the original (pre-embed) H.264 video.
        circuits_dir:        Path to circuits/ directory (ZK build artifacts).
        secret_key:          32-byte secret key used during embedding.
        message_length:      Expected message length in bytes.
        max_modifications_per_block: Must match value used in embed() (default 1).
        chaos_key:           Must match the chaos_key passed to embed() — if embed()
                             was called with chaos_key, pass the same value here.

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

    # 2. Get safe positions (must be the same order used during embedding)
    safety = CAVLCSafetyFilter()
    safe_positions = safety.get_safe_positions(
        coefficients,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
    )

    # 2b. Chaos: Logistic Map — apply the same position shuffle as embed()
    chaos: Optional[ChaosTransformer] = None
    original_bit_count = blob_bit_length(b"\x00" * message_length)
    if chaos_key is not None:
        chaos = ChaosTransformer(chaos_key)
        safe_positions = chaos.shuffle_positions(safe_positions)
        logger.info(
            "[Chaos] Logistic Map shuffle applied to %d positions",
            len(safe_positions),
        )

    # 3. Compute how many bits to extract
    if chaos is not None:
        # Must extract M² bits (padded) to correctly unscramble
        padded_bits = ChaosTransformer.padded_bit_count(original_bit_count)
        # Round up to byte boundary for extract_bits_direct
        extract_bit_count = math.ceil(padded_bits / 8) * 8
    else:
        extract_bit_count = original_bit_count

    # 3a. Extract bits from stego video
    extracted_blob = extract_bits_direct(
        stego_video_path,
        safe_positions,
        frame_verified_data,
        nC_map,
        extract_bit_count,
        max_modifications_per_block=max_modifications_per_block,
    )

    # 3b. Chaos: Arnold Cat Map — unscramble extracted bits
    if chaos is not None:
        extracted_blob = chaos.unscramble(extracted_blob, original_bit_count)
        logger.info("[Chaos] Arnold Cat Map inverse applied (k=%d)", chaos.arnold_k)

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
        bits_extracted=extract_bit_count,
    )
