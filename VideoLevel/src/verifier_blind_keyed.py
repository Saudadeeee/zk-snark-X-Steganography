"""
verifier_blind_keyed.py - Experimental keyed blind verification.

This path aims to remove sidecar metadata entirely:
  stego video + secret key + message length -> derive positions -> extract -> verify

It is intentionally conservative and currently targets fixed-payload / no-chaos
operating contracts first.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from .bitstream.bitstream_ops import BitstreamReconstructor
from .bitstream.h264 import H264BitstreamParser
from .blind_sync import BlindPublicMetadata, derive_blind_positions_validated_pool_proxy
from .core.pipeline import extract_all_idr_blocks, extract_bits_direct
from .verifier import VerifyResult
from .zk_proof import ZKSnarkBridge, blob_bit_length, unpack


@lru_cache(maxsize=4)
def _get_bridge(circuits_dir: str) -> ZKSnarkBridge:
    return ZKSnarkBridge(circuits_dir)


def verify_blind_keyed(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[VerifyResult, BlindPublicMetadata]:
    """
    Experimental blind verification without sidecar metadata.

    Current assumptions:
    - fixed-payload contract determined by message_length
    - no external positions or manifest file
    - no chaos layer in this experimental path
    """
    required_bits = blob_bit_length(b"\x00" * message_length)
    blind_positions, metadata = derive_blind_positions_validated_pool_proxy(
        stego_video_path,
        secret_key,
        required_bits=required_bits,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )

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

    extracted_blob = extract_bits_direct(
        stego_video_path=stego_video_path,
        embed_safe_positions=blind_positions,
        frame_verified_data=frame_verified_data,
        nC_map=nC_map,
        payload_bits=required_bits,
        max_modifications_per_block=1,
    )

    try:
        message, proof_bytes = unpack(extracted_blob)
    except ValueError:
        return VerifyResult(
            valid=False,
            message=None,
            proof_dict=None,
            public_dict=None,
            bits_extracted=required_bits,
        ), metadata

    bridge = _get_bridge(circuits_dir)
    proof_dict = bridge.bytes_to_proof(proof_bytes)
    public_signals = bridge._build_public_signals(message, secret_key)
    is_valid = bridge.verify(proof_dict, public_signals)
    if is_valid and len(message) != message_length:
        is_valid = False

    return VerifyResult(
        valid=is_valid,
        message=message if is_valid else None,
        proof_dict=proof_dict,
        public_dict=public_signals,
        bits_extracted=required_bits,
    ), metadata
