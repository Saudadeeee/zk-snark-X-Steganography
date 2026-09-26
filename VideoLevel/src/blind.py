"""Sidecar-free CAVLC blind-mode contract.

Blind mode deliberately uses only sign changes at deterministic, non-trailing
AC coefficients.  Candidate membership is based on coefficient support and
magnitude, not sign or LSB parity, so the same keyed order can be derived from
the stego stream without the cover stream or a positions sidecar.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .blind_sync import (
    derive_blind_positions,
    derive_blind_positions_from_analysis,
    select_streaming_blind_positions,
)
from .core.analysis_cache import load_or_build_video_analysis
from .core.pipeline import (
    extract_bits_direct,
    extract_selected_sign_bits_streaming,
    iter_idr_luma_analysis,
    patch_selected_sign_positions_streaming,
)
from .bitstream.bitstream_ops import BitstreamReconstructor
from .embedder import EmbedResult, embed
from .verifier import VerifyResult
from .zk_proof import ZKSnarkBridge, pack, unpack


PROOF_BYTES = 129


@dataclass(frozen=True)
class StreamingBlindEmbedResult:
    """Evidence returned by the bounded-memory blind embedding path."""

    output_path: str
    bits_embedded: int
    positions: tuple[tuple[int, int, int], ...]
    patch_stats: dict[str, int]


def blind_payload_bits(*, message_length: int) -> int:
    """Return the fixed packed-payload size derivable by a blind receiver."""
    if message_length <= 0:
        raise ValueError("message_length must be positive")
    return (4 + message_length + PROOF_BYTES) * 8


def sign_invariant_positions(
    stable_positions: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    """Convert stable AC indices to the sign-encoding representation.

    ``PayloadEmbedder`` denotes a sign bit at zigzag index ``i`` as ``~i``.
    Sign-only embedding preserves support and magnitude, which is necessary
    for cover-free candidate re-derivation.
    """
    return [
        (int(mb), int(block), int(index) if int(index) < 0 else ~int(index))
        for mb, block, index in stable_positions
    ]


def derive_blind_sign_positions(
    video_path: str,
    secret_key: bytes,
    required_bits: int,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> list[tuple[int, int, int]]:
    positions, _metadata = derive_blind_positions(
        video_path,
        secret_key,
        required_bits,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )
    return sign_invariant_positions(positions)


def _derive_blind_sign_positions_from_analysis(
    analysis: tuple,
    secret_key: bytes,
    required_bits: int,
) -> list[tuple[int, int, int]]:
    positions, _metadata = derive_blind_positions_from_analysis(
        analysis,
        secret_key=secret_key,
        required_bits=required_bits,
    )
    return sign_invariant_positions(positions)


def derive_blind_sign_positions_streaming(
    video_path: str,
    secret_key: bytes,
    required_bits: int,
) -> list[tuple[int, int, int]]:
    """Derive v2 blind sign positions without loading full-video analysis."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Stego video not found: {video_path}")
    records = iter_idr_luma_analysis(video_path, BitstreamReconstructor())
    return select_streaming_blind_positions(
        records,
        secret_key=secret_key,
        required_bits=required_bits,
    )


def _bytes_to_bits(payload: bytes) -> list[int]:
    return [
        (byte >> shift) & 1
        for byte in payload
        for shift in range(7, -1, -1)
    ]


def embed_blind_streaming(
    video_path: str,
    message: bytes,
    output_path: str,
    circuits_dir: str,
    secret_key: bytes,
) -> StreamingBlindEmbedResult:
    """Embed a sidecar-free proof using three bounded-memory CAVLC passes."""
    if not isinstance(message, bytes) or not message:
        raise ValueError("message must be non-empty bytes")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")

    bridge = ZKSnarkBridge(circuits_dir)
    proof, _public = bridge.generate_proof_for_payload(message, secret_key)
    payload = pack(message, bridge.proof_to_bytes(proof))
    required_bits = len(payload) * 8
    positions = derive_blind_sign_positions_streaming(video_path, secret_key, required_bits)
    if len(positions) < required_bits:
        raise RuntimeError(
            f"streaming blind contract has {len(positions)} sign-stable positions; requires {required_bits}"
        )
    position_bits = dict(zip(positions, _bytes_to_bits(payload), strict=True))
    patch_stats = patch_selected_sign_positions_streaming(video_path, output_path, position_bits)
    return StreamingBlindEmbedResult(
        output_path=output_path,
        bits_embedded=required_bits,
        positions=tuple(positions),
        patch_stats=patch_stats,
    )


def verify_blind_streaming(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
) -> VerifyResult:
    """Recover and verify v2 blind payloads without cover, cache, or sidecars."""
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    required_bits = blind_payload_bits(message_length=message_length)
    positions = derive_blind_sign_positions_streaming(stego_video_path, secret_key, required_bits)
    if len(positions) < required_bits:
        return VerifyResult(False, None, None, None, 0)
    try:
        blob = extract_selected_sign_bits_streaming(stego_video_path, positions)
        message, proof_bytes = unpack(blob)
        bridge = ZKSnarkBridge(circuits_dir)
        proof = bridge.bytes_to_proof(proof_bytes)
        public = bridge._build_public_signals(message, secret_key)
        valid = bridge.verify(proof, public) and len(message) == message_length
    except (RuntimeError, ValueError, AssertionError):
        return VerifyResult(False, None, None, None, required_bits)
    return VerifyResult(valid, message if valid else None, proof if valid else None, public if valid else None, required_bits)


def embed_blind(
    video_path: str,
    message: bytes,
    output_path: str,
    circuits_dir: str,
    secret_key: bytes,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> EmbedResult:
    """Embed with a deterministic sign-only position contract.

    The normal embedder still emits audit sidecars. They are deliberately not
    read by :func:`verify_blind`; they may be deleted after embedding.
    """
    if not isinstance(message, bytes) or not message:
        raise ValueError("message must be non-empty bytes")
    required_bits = blind_payload_bits(message_length=len(message))
    analysis = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    positions = _derive_blind_sign_positions_from_analysis(
        analysis,
        secret_key,
        required_bits,
    )
    if len(positions) < required_bits:
        raise RuntimeError(
            f"blind contract has {len(positions)} sign-stable positions; requires {required_bits}"
        )
    return embed(
        video_path=video_path,
        message=message,
        output_path=output_path,
        circuits_dir=circuits_dir,
        secret_key=secret_key,
        max_modifications_per_block=1,
        precomputed_positions=positions,
        trust_precomputed_positions=True,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
        precomputed_analysis=analysis,
    )


def verify_blind(
    stego_video_path: str,
    circuits_dir: str,
    secret_key: bytes,
    message_length: int,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> VerifyResult:
    """Recover and verify without original cover or any sidecar files."""
    if not os.path.isfile(stego_video_path):
        raise FileNotFoundError(f"Stego video not found: {stego_video_path}")
    if not os.path.isdir(circuits_dir):
        raise FileNotFoundError(f"circuits_dir not found: {circuits_dir}")
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    required_bits = blind_payload_bits(message_length=message_length)
    positions = derive_blind_sign_positions(
        stego_video_path,
        secret_key,
        required_bits,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )
    if len(positions) < required_bits:
        return VerifyResult(False, None, None, None, 0)
    (
        _coefficients,
        frame_verified_data,
        nC_map,
        _nal_length_map,
        _t1_override_map,
        _safe_positions,
    ) = load_or_build_video_analysis(
        stego_video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    blob = extract_bits_direct(
        stego_video_path,
        positions,
        frame_verified_data,
        nC_map,
        required_bits,
        max_modifications_per_block=1,
    )
    try:
        message, proof_bytes = unpack(blob)
    except ValueError:
        return VerifyResult(False, None, None, None, required_bits)
    bridge = ZKSnarkBridge(circuits_dir)
    proof = bridge.bytes_to_proof(proof_bytes)
    public = bridge._build_public_signals(message, secret_key)
    valid = bridge.verify(proof, public) and len(message) == message_length
    return VerifyResult(valid, message if valid else None, proof if valid else None, public if valid else None, required_bits)
