"""
verifier_blind.py - Near-blind verification mode.

Reduces dependency on the original cover video by deriving extraction metadata
from sidecars and rebuilding the extraction context from the stego video only.
"""

import logging
import math
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

from .bitstream.bitstream_ops import BitstreamReconstructor
from .bitstream.h264 import H264BitstreamParser
from .core.chaos import ChaosTransformer
from .core.pipeline import extract_all_idr_blocks, extract_bits_direct
from .core.matrix_embedding import (
    MATRIX_EMBEDDING_STRATEGY,
    bits_to_bytes,
    bytes_to_bits,
    extract_hamming73,
    matrix_carrier_bit_count,
)
from .verifier import VerifyResult, _load_sidecar_data
from .zk_proof import ZKSnarkBridge, unpack, blob_bit_length
from .lattice_pq import LatticeReceipt, lattice_reference_bit_length, unpack_lattice_reference
from .manifest import compute_file_hash, hash_positions
from .stream_profile import analyze_stream_profile
from .exceptions import UnsupportedStreamError


MAX_MESSAGE_BYTES = 999_999


@lru_cache(maxsize=4)
def _get_bridge(circuits_dir: str) -> ZKSnarkBridge:
    return ZKSnarkBridge(circuits_dir)


def verify_near_blind(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    manifest_public_key: bytes,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> VerifyResult:
    """
    Verify ZK proof without the original cover video.

    This mode requires sidecar metadata produced during embedding:
    - manifest.json
    - positions.json
    - meta.json or manifest payload bit count
    """
    if not os.path.isfile(stego_video_path):
        raise FileNotFoundError(f"Stego video not found: {stego_video_path}")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if manifest_public_key is None:
        raise ValueError("manifest_public_key is required")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    if not isinstance(message_length, int) or not 0 < message_length <= MAX_MESSAGE_BYTES:
        raise ValueError(f"message_length must be between 1 and {MAX_MESSAGE_BYTES}")

    stego_profile = analyze_stream_profile(stego_video_path)
    if not stego_profile.supported:
        raise UnsupportedStreamError(
            stego_profile.rejection_reason or "unsupported H.264 stego stream",
            profile=stego_profile.profile,
            entropy_mode=stego_profile.entropy_mode,
        )

    positions, payload_bits, manifest = _load_sidecar_data(stego_video_path)
    if manifest is None:
        raise RuntimeError(
            f"Manifest not found or invalid for {stego_video_path}. "
            "Near-blind verification requires manifest.json."
        )
    if not positions:
        raise RuntimeError(
            f"Positions not found or invalid for {stego_video_path}. "
            "Near-blind verification requires positions.json."
        )

    expected_key_size = 1952 if manifest.signature_algorithm == "ml-dsa-65" else 32
    if not isinstance(manifest_public_key, bytes) or len(manifest_public_key) != expected_key_size:
        raise ValueError(f"manifest_public_key must be {expected_key_size} bytes for the signed manifest")
    if not manifest.verify_signature(manifest_public_key):
        raise RuntimeError("Manifest signature verification failed")
    if manifest.video.stego_file_hash != compute_file_hash(stego_video_path):
        raise RuntimeError("Stego file hash does not match the signed manifest")
    if manifest.embedding.positions_count != len(positions):
        raise RuntimeError("Positions count does not match the signed manifest")
    if manifest.embedding.positions_hash != hash_positions(positions):
        raise RuntimeError("Positions sidecar hash does not match the signed manifest")
    if manifest.payload.message_length != message_length:
        raise RuntimeError("Requested message length does not match the signed manifest")
    if manifest.payload.chaos_enabled != (chaos_key is not None):
        raise RuntimeError("Chaos configuration does not match the signed manifest")
    if manifest.embedding.strategy not in {"t1_sign_flip", MATRIX_EMBEDDING_STRATEGY}:
        raise RuntimeError("Signed embedding strategy is unsupported")
    if manifest.embedding.max_modifications_per_block != max_modifications_per_block:
        raise RuntimeError("Modification limit does not match the signed manifest")

    parser = H264BitstreamParser(stego_video_path)
    parser.parse()
    rec = BitstreamReconstructor()
    (
        _coefficients,
        frame_verified_data,
        nC_map,
        _nal_length_map,
        _t1_override_map,
    ) = extract_all_idr_blocks(
        stego_video_path,
        rec,
        parser=parser,
    )

    is_lattice = manifest.proof.proof_system == "ml-dsa-65-attestation"
    original_bit_count = (
        lattice_reference_bit_length(b"\x00" * message_length)
        if is_lattice else blob_bit_length(b"\x00" * message_length)
    )
    chaos: Optional[ChaosTransformer] = None
    if chaos_key is not None:
        chaos = ChaosTransformer(chaos_key)

    extract_bit_count = int(manifest.payload.bits_required)
    if payload_bits is not None and int(payload_bits) != extract_bit_count:
        raise RuntimeError("Payload bit count does not match the signed manifest")
    carrier_bit_count = (
        matrix_carrier_bit_count(extract_bit_count)
        if manifest.embedding.strategy == MATRIX_EMBEDDING_STRATEGY
        else extract_bit_count
    )
    if extract_bit_count <= 0 or carrier_bit_count > len(positions):
        raise RuntimeError("Signed payload bit count is outside the positions sidecar bounds")
    expected_bit_count = (
        math.ceil(ChaosTransformer.padded_bit_count(original_bit_count) / 8) * 8
        if chaos is not None
        else original_bit_count
    )
    if extract_bit_count != expected_bit_count:
        raise RuntimeError("Signed payload bit count is inconsistent with the message length and chaos mode")

    extracted_carriers = extract_bits_direct(
        stego_video_path=stego_video_path,
        embed_safe_positions=[tuple(int(v) for v in pos) for pos in positions],
        frame_verified_data=frame_verified_data,
        nC_map=nC_map,
        payload_bits=carrier_bit_count,
        max_modifications_per_block=max_modifications_per_block,
    )
    extracted_blob = (
        bits_to_bytes(extract_hamming73(
            bytes_to_bits(extracted_carriers, carrier_bit_count), extract_bit_count
        ))
        if manifest.embedding.strategy == MATRIX_EMBEDDING_STRATEGY
        else extracted_carriers
    )

    if chaos is not None:
        extracted_blob = chaos.unscramble(extracted_blob, original_bit_count)
        logger.info("[Chaos] Arnold Cat Map inverse applied (k=%d)", chaos.arnold_k)

    try:
        if is_lattice:
            message, proof_bytes = unpack_lattice_reference(extracted_blob)
        else:
            message, proof_bytes = unpack(extracted_blob)
    except ValueError:
        return VerifyResult(
            valid=False,
            message=None,
            proof_dict=None,
            public_dict=None,
            bits_extracted=extract_bit_count,
        )

    if is_lattice:
        try:
            receipt = LatticeReceipt.load(f"{stego_video_path}.lattice.json")
            is_valid = receipt.commitment() == proof_bytes and receipt.verify(message, manifest_public_key)
            proof_dict = receipt.to_dict()
        except (OSError, ValueError, KeyError):
            is_valid = False
            proof_dict = None
        return VerifyResult(is_valid, message if is_valid else None, proof_dict,
                            {"signature_algorithm": "ML-DSA-65"} if is_valid else None, extract_bit_count)

    bridge = _get_bridge(circuits_dir)
    proof_dict = bridge.bytes_to_proof(proof_bytes)
    public_signals = bridge._build_public_signals(message, secret_key)
    is_valid = bridge.verify(proof_dict, public_signals)

    if is_valid and len(message) != message_length:
        logger.warning(
            "[NearBlind] Extracted message length mismatch: got=%d expected=%d",
            len(message),
            message_length,
        )
        is_valid = False

    return VerifyResult(
        valid=is_valid,
        message=message if is_valid else None,
        proof_dict=proof_dict,
        public_dict=public_signals,
        bits_extracted=extract_bit_count,
    )
