"""
verifier_blind.py — Near-blind verification mode.

Reduces dependency on original cover video by deriving positions from manifest
and reconstructing coefficient map from stego video only.

Quick start:
    from src.verifier_blind import verify_near_blind, VerifyResult

    result = verify_near_blind(
        stego_video_path = "data/output/stego.h264",
        circuits_dir     = "circuits/",
        secret_key       = secret_key,
        message_length   = len(original_message),
    )
"""

import logging
import os
from functools import lru_cache
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

from .bitstream.h264 import H264BitstreamParser, MacroblockParser
from .bitstream.cavlc import CAVLCDecoder
from .core.stego import PayloadEmbedder
from .core.chaos import ChaosTransformer
from .zk_proof import ZKSnarkBridge, unpack, blob_bit_length
from .manifest import StegoManifest
from .verifier import VerifyResult


@lru_cache(maxsize=4)
def _get_bridge(circuits_dir: str) -> ZKSnarkBridge:
    return ZKSnarkBridge(circuits_dir)


def _parse_stego_idr_coefficients(stego_path: str) -> list:
    """Parse only T1 coefficients from stego video IDR frames.

    Returns list of (mb_idx, block_idx, coeff_idx, value) tuples.
    This is a minimal parse focusing only on trailing-ones positions.
    """
    parser = H264BitstreamParser(stego_path)
    t1_coeffs = []

    for nal in parser.nal_units:
        if nal.nal_ref_idc == 0:
            continue  # Skip non-reference NALs

        if nal.nal_type not in (1, 5, 19, 20):
            continue  # Not IDR or slice

        mb_parser = MacroblockParser(parser.bitstream, parser.sps, parser.pps)
        for mb_idx in range(mb_parser.mb_width * mb_parser.mb_height):
            mb_data = mb_parser.parse_macroblock()

            # Parse 4x4 luma blocks
            for blk_idx in range(16):
                if mb_data.get(f"luma_{blk_idx}_block_type") != "Intra_4x4":
                    continue

                coeffs = mb_data.get(f"luma_{blk_idx}_coeffs", [])
                for cidx, coeff in enumerate(coeffs):
                    if abs(coeff) == 1:  # T1 position
                        t1_coeffs.append((mb_idx, blk_idx, cidx, coeff))

    return t1_coeffs


def verify_near_blind(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    max_modifications_per_block: int = 1,
    chaos_key: Optional[bytes] = None,
) -> VerifyResult:
    """
    Verify ZK proof with minimal cover dependency.

    This mode:
    1. Loads manifest.json for positions and metadata
    2. Parses stego video to extract coefficient values
    3. Extracts payload bits from specified positions
    4. Verifies ZK proof

    Does NOT require full cover analysis (no extract_all_idr_blocks).

    Args:
        stego_video_path: Path to stego H.264 video.
        circuits_dir: Path to circuits directory.
        secret_key: 32-byte secret key for proof verification.
        message_length: Expected message byte length.
        max_modifications_per_block: Same as embed (default 1).
        chaos_key: Optional chaos key (must match embed).

    Returns:
        VerifyResult

    Raises:
        FileNotFoundError: If stego video or circuits not found.
        RuntimeError: If manifest missing or invalid.
    """
    # Input validation
    if not os.path.isfile(stego_video_path):
        raise FileNotFoundError(f"Stego video not found: {stego_video_path}")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    if message_length <= 0:
        raise ValueError("message_length must be a positive integer")

    # Load manifest
    manifest_path = f"{stego_video_path}.manifest.json"
    if not os.path.isfile(manifest_path):
        raise RuntimeError(
            f"Manifest not found: {manifest_path}. "
            "Near-blind verification requires manifest.json."
        )

    manifest = StegoManifest.load(manifest_path)

    # Verify manifest integrity if signed
    if manifest.signature:
        # TODO: Verify signature when signing implemented
        logger.info("[Manifest] Signed manifest detected (signature verification not implemented)")

    # Validate manifest matches parameters
    if manifest.payload.chaos_enabled != (chaos_key is not None):
        logger.warning(
            "[Manifest] Chaos mismatch: manifest says %s, chaos_key %s provided",
            manifest.payload.chaos_enabled, "is" if chaos_key else "is not"
        )

    # Parse stego video T1 coefficients
    logger.info("[Stego] Parsing T1 coefficients from stego video...")
    stego_coeffs = _parse_stego_idr_coefficients(stego_video_path)

    # Build coefficient map for extraction
    # Format: coefficients[idr][mb][block] = [coeff_values]
    coeff_map = {}
    for mb_idx, blk_idx, cidx, val in stego_coeffs:
        idr_key = 0  # Simplified: assume single IDR or aggregate
        if idr_key not in coeff_map:
            coeff_map[idr_key] = {}
        if mb_idx not in coeff_map[idr_key]:
            coeff_map[idr_key][mb_idx] = {}
        if blk_idx not in coeff_map[idr_key][mb_idx]:
            coeff_map[idr_key][mb_idx][blk_idx] = []
        coeff_map[idr_key][mb_idx][blk_idx].append(val)

    # Load positions from manifest (or positions.json for backward compat)
    pos_path = f"{stego_video_path}.positions.json"
    if not os.path.isfile(pos_path):
        raise RuntimeError(f"Positions not found: {pos_path}")

    import json
    with open(pos_path, "r", encoding="utf-8") as f:
        positions = [tuple(int(v) for v in row) for row in json.load(f)]

    logger.info("[Manifest] Loaded %d positions from manifest", len(positions))

    # Extract payload bits
    embedder = PayloadEmbedder(max_modifications_per_block=max_modifications_per_block)

    # Reconstruct coefficient list in expected format
    # Flatten coeff_map to list of (mb, block, coeffs) tuples
    coefficients = []
    for idr in coeff_map.values():
        for mb_idx, blocks in idr.items():
            for blk_idx, coeffs in blocks.items():
                coefficients.append((mb_idx, blk_idx, coeffs))

    # Extract bits
    logger.info("[Extract] Extracting payload bits from stego...")
    extracted_blob = embedder.extract_payload(
        coefficients,
        positions,
        manifest.payload.bits_required,
    )

    # Un-chaos if needed
    if chaos_key is not None:
        chaos = ChaosTransformer(chaos_key)
        extracted_blob = chaos.descramble(extracted_blob)

    # Verify ZK proof
    bridge = _get_bridge(circuits_dir)

    try:
        message, proof_bytes = unpack(extracted_blob)
        proof_dict = bridge.bytes_to_proof(proof_bytes)

        # Rebuild public signals for verification
        payload_hash = _compute_payload_hash(message)
        commitment = _compute_commitment(payload_hash, secret_key)

        public_dict = {
            "payload_hash": payload_hash,
            "commitment": commitment,
            "payload_length": len(message),
        }

        valid = bridge.verify(proof_dict, public_dict)

        if valid and len(message) == message_length:
            logger.info("[ZK] Proof verified! Message: %s", message)
            return VerifyResult(
                valid=True,
                message=message,
                proof_dict=proof_dict,
                public_dict=public_dict,
                bits_extracted=manifest.payload.bits_embedded,
            )
        else:
            logger.warning("[ZK] Proof verification failed or message length mismatch")
            return VerifyResult(
                valid=False,
                message=None,
                proof_dict=proof_dict,
                public_dict=public_dict,
                bits_extracted=manifest.payload.bits_embedded,
            )

    except Exception as e:
        logger.error("[ZK] Extraction/verification error: %s", e)
        return VerifyResult(
            valid=False,
            message=None,
            proof_dict=None,
            public_dict=None,
            bits_extracted=0,
        )


def _compute_payload_hash(message: bytes) -> int:
    """Compute SHA256 hash and convert to int."""
    import hashlib
    h = hashlib.sha256(message).hexdigest()
    return int(h, 16)


def _compute_commitment(payload_hash: int, secret_key: bytes) -> int:
    """Compute SHA256(payload_hash || secret)."""
    import hashlib
    payload_bytes = payload_hash.to_bytes(32, "big")
    h = hashlib.sha256(payload_bytes + secret_key).hexdigest()
    return int(h, 16)