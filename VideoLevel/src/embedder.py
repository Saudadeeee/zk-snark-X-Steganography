"""
embedder.py — Public API: Embed a ZK proof into an H.264 video.

Quick start:
    from src.embedder import embed, EmbedResult

    result = embed(
        video_path    = "data/encoded/foreman_cif_g8.h264",
        message       = b"my secret message",
        output_path   = "data/output/stego.h264",
        circuits_dir  = "circuits/",
        secret_key    = os.urandom(32),
    )
    print(f"Embedded {result.bits_embedded} bits")
    print(f"Capacity: {result.capacity_bits} bits available")
"""

import logging
import os
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from .core.pipeline        import extract_all_idr_blocks
from .core.stego           import PayloadEmbedder
from .bitstream.bitstream_ops import BitstreamReconstructor
from .exceptions           import InsufficientCapacityError
from .zk_proof             import ZKSnarkBridge, pack


@dataclass
class EmbedResult:
    """Result returned by embed()."""
    bits_embedded:  int    # Number of payload bits embedded
    capacity_bits:  int    # Total T1 bits available (before FFmpeg filter)
    output_path:    str    # Path to the output stego video
    proof_dict:     dict   # Raw snarkjs proof dict
    public_dict:    dict   # Public signals dict (for verification)


def embed(
    video_path:   str,
    message:      bytes,
    output_path:  str,
    circuits_dir: str,
    secret_key:   bytes,
    max_modifications_per_block: int = 1,
    ffmpeg_validate: bool = False,
) -> EmbedResult:
    """
    Embed a Groth16 ZK proof for `message` into an H.264 video.

    Pipeline:
        1. Generate ZK proof  (snarkjs Groth16, via Node.js)
        2. Pack payload blob  [4B len][message][256B proof]
        3. Parse H.264 video  extract IDR coefficients + bit offsets
        4. Safety filter      find safe trailing-ones positions
        5. Embed payload      flip T1 sign bits (descending order)
        6. Reconstruct video  patch bitstream at tracked offsets

    Args:
        video_path:   Input H.264 video path.
        message:      Secret message bytes to commit to.
        output_path:  Output stego H.264 video path.
        circuits_dir: Path to circuits/ directory (ZK build artifacts).
        secret_key:   32-byte secret key (never embedded, used for commitment).
        max_modifications_per_block: T1 flips per 4×4 block (default 1).
        ffmpeg_validate: Enable per-position FFmpeg pixel validation.
                         Slower but guarantees no visible artefacts.

    Returns:
        EmbedResult

    Raises:
        FileNotFoundError: If video_path or circuits_dir does not exist.
        ValueError: If message is empty or secret_key is not 32 bytes.
        RuntimeError: If video has no IDR frames or capacity is insufficient.
    """
    # --- Input validation ---
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if not isinstance(message, bytes) or len(message) == 0:
        raise ValueError("message must be non-empty bytes")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    if max_modifications_per_block < 1 or max_modifications_per_block > 8:
        raise ValueError("max_modifications_per_block must be between 1 and 8")
    if ffmpeg_validate and shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg_validate=True but 'ffmpeg' was not found on PATH."
        )

    # 1. Generate ZK proof
    bridge = ZKSnarkBridge(circuits_dir)
    proof_dict, public_dict = bridge.generate_proof_for_payload(message, secret_key)
    proof_bytes = bridge.proof_to_bytes(proof_dict)

    # 2. Pack payload blob
    payload_blob = pack(message, proof_bytes)

    # 3. Parse H.264 — extract IDR coefficients + metadata
    rec = BitstreamReconstructor()
    coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map = \
        extract_all_idr_blocks(video_path, rec)

    # 4. Optional FFmpeg validator
    validator = cleanup = None
    if ffmpeg_validate:
        validator, cleanup = rec.make_ffmpeg_position_validator(
            video_path, coefficients, frame_verified_data
        )

    # 5. Embed payload
    embedder = PayloadEmbedder(max_modifications_per_block=max_modifications_per_block)
    modified, bits_embedded = embedder.embed_payload(
        coefficients, payload_blob,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
        ffmpeg_validator=validator,
    )

    if cleanup:
        cleanup()

    required_bits = len(payload_blob) * 8
    if bits_embedded < required_bits:
        raise InsufficientCapacityError(
            required_bits=required_bits,
            available_bits=bits_embedded,
        )

    # 6. Reconstruct stego video
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    rec2 = BitstreamReconstructor()
    rec2.reconstruct_video(
        video_path, modified, output_path,
        frame_verified_data=frame_verified_data,
    )

    capacity = sum(
        1 for _, _, coeffs in coefficients for v in coeffs if abs(v) == 1
    )

    return EmbedResult(
        bits_embedded=bits_embedded,
        capacity_bits=capacity,
        output_path=output_path,
        proof_dict=proof_dict,
        public_dict=public_dict,
    )
