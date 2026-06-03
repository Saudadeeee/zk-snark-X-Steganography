"""
embedder.py — Public API: Embed a ZK proof into an H.264 video.

Quick start:
    from src.embedder import embed, EmbedResult

    result = embed(
        video_path    = "data/encoded/foreman_cif_q22_g1.h264",
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
import json
import shutil
from collections import defaultdict
from functools import lru_cache
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

from .core.analysis_cache  import (
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
)
from .core.stego           import PayloadEmbedder
from .core.chaos           import ChaosTransformer
from .bitstream.bitstream_ops import BitstreamReconstructor, BitstreamPatcher
from .exceptions           import InsufficientCapacityError
from .stream_profile       import analyze_stream_profile
from .zk_proof             import ZKSnarkBridge, pack
from .manifest             import (
    StegoManifest,
    PayloadMetadata,
    EmbeddingMetadata,
    VideoMetadata,
    ProofMetadata,
    compute_file_hash,
)


@lru_cache(maxsize=4)
def _get_bridge(circuits_dir: str) -> ZKSnarkBridge:
    return ZKSnarkBridge(circuits_dir)


def _prune_patchable_positions(
    safe_positions: list[tuple[int, int, int]],
    frame_verified_data: dict,
    required_bits: int,
) -> list[tuple[int, int, int]]:
    """
    Keep only positions whose blocks are bitstream-patchable.

    This validates candidate blocks lazily and stops once enough positions
    have been retained for the payload.
    """
    patcher = BitstreamPatcher()
    block_order: list[tuple[int, int]] = []
    block_to_positions: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    seen_blocks: set[tuple[int, int]] = set()

    for pos in safe_positions:
        key = (int(pos[0]), int(pos[1]))
        block_to_positions[key].append((int(pos[0]), int(pos[1]), int(pos[2])))
        if key not in seen_blocks:
            seen_blocks.add(key)
            block_order.append(key)

    idr_desc = sorted(frame_verified_data.keys(), reverse=True)
    retained: list[tuple[int, int, int]] = []
    idr_context: dict[int, tuple[dict, dict, bytes]] = {}

    for idr_off, (g_off, _g_blk, nal_rbsp) in frame_verified_data.items():
        local_offsets = {
            (gmb - idr_off, gblk): od
            for (gmb, gblk), od in g_off.items()
            if gblk < 16 and od.get("bit_length") not in (None, 0)
        }
        end_to_block = {
            od["end_bit"]: ((gmb - idr_off, gblk), od)
            for (gmb, gblk), od in g_off.items()
            if gblk < 16 and "end_bit" in od
        }
        idr_context[idr_off] = (local_offsets, end_to_block, nal_rbsp)

    for mb, blk in block_order:
        idr_off = next((off for off in idr_desc if off <= mb), None)
        if idr_off is None:
            continue
        local_offsets, end_to_block, nal_rbsp = idr_context.get(idr_off, ({}, {}, b""))
        local_key = (mb - idr_off, blk)
        match = patcher.validate_block_patchability(
            nal_rbsp,
            local_key,
            local_offsets.get(local_key, {}),
            end_to_block,
        )
        if match is None:
            continue
        retained.extend(block_to_positions[(mb, blk)])
        if len(retained) >= required_bits:
            break

    return retained


def _limit_positions_per_block(
    positions: list[tuple[int, int, int]],
    max_modifications_per_block: int,
) -> list[tuple[int, int, int]]:
    """
    Keep at most N positions per (mb, blk) while preserving global order.
    """
    if max_modifications_per_block <= 0:
        return []
    if max_modifications_per_block >= 8:
        return list(positions)

    counts: dict[tuple[int, int], int] = {}
    limited: list[tuple[int, int, int]] = []
    for pos in positions:
        key = (int(pos[0]), int(pos[1]))
        used = counts.get(key, 0)
        if used >= max_modifications_per_block:
            continue
        limited.append((int(pos[0]), int(pos[1]), int(pos[2])))
        counts[key] = used + 1
    return limited


@dataclass
class EmbedResult:
    """Result returned by embed()."""
    bits_embedded:       int           # Number of payload bits embedded
    capacity_bits:       int           # Total T1 bits available (before FFmpeg filter)
    output_path:         str           # Path to the output stego video
    proof_dict:          dict          # Raw snarkjs proof dict
    public_dict:         dict          # Public signals dict (for verification)
    stream_class:        Optional[str] = None
    raw_safe_bits:       Optional[int] = None
    patchable_usable_bits: Optional[int] = None
    ffmpeg_validated_bits: Optional[int] = None
    requested_position_bits: Optional[int] = None
    applied_position_bits: Optional[int] = None
    chaos_original_bits: Optional[int] = None  # Set when chaos_key used (orig bit count)
    used_positions:      Optional[list[tuple[int, int, int]]] = None  # Final positions actually used for embedding


def embed(
    video_path:   str,
    message:      bytes,
    output_path:  str,
    circuits_dir: str,
    secret_key:   bytes,
    max_modifications_per_block: int = 1,
    ffmpeg_validate: bool = False,
    chaos_key: Optional[bytes] = None,
    precomputed_positions: Optional[list[tuple[int, int, int]]] = None,
    trust_precomputed_positions: bool = False,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> EmbedResult:
    """
    Embed a Groth16 ZK proof for `message` into an H.264 video.

    Pipeline:
        1. Generate ZK proof  (snarkjs Groth16, via Node.js)
        2. Pack payload blob  [4B len][message][129B proof]
       2b. [Chaos] Arnold Cat Map scrambles payload bits  (if chaos_key)
        3. Parse H.264 video  extract IDR coefficients + bit offsets
        4. Safety filter      find safe trailing-ones positions
       4b. [Chaos] Logistic Map shuffles embedding positions (if chaos_key)
        5. Embed payload      flip T1 sign bits
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
        chaos_key:    Optional bytes key to enable chaos math transforms.
                      When set, Arnold Cat Map scrambles payload bits and
                      Logistic Map shuffles the embedding position order,
                      making the hidden data resist steganalysis.
                      Pass the same key to verify() for correct extraction.
        precomputed_positions: Optional externally supplied operating positions.
                      When provided, these are used directly and bypass the
                      default safe-position ordering / pruning flow.
        trust_precomputed_positions: When True, keep externally supplied
                      operating positions as the authoritative bit budget
                      instead of re-inferring usable bits from applied_block_keys.
                      Intended for benchmark-grade operating points that have
                      already been validated end-to-end.
        use_analysis_cache: Reuse cached cover-video analysis when available.
                            Strongly recommended for app/runtime usage.
        force_analysis_refresh: Ignore cached cover analysis and rebuild it.
        analysis_cache_dir: Optional custom directory for analysis cache files.

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
    stream_profile = analyze_stream_profile(video_path)
    if not stream_profile.is_all_intra:
        logger.warning(
            "[Embed] Stream classified as %s; current strongest operating regime remains all-intra H.264/CAVLC",
            stream_profile.inferred_gop_class,
        )

    # 1. Generate ZK proof
    bridge = _get_bridge(circuits_dir)
    proof_dict, public_dict = bridge.generate_proof_for_payload(message, secret_key)
    proof_bytes = bridge.proof_to_bytes(proof_dict)

    # 2. Pack payload blob  [4B len][message][129B compressed proof]
    payload_blob = pack(message, proof_bytes)
    original_bit_count = len(payload_blob) * 8

    # 2b. Chaos: Arnold Cat Map — scramble payload bits
    chaos: Optional[ChaosTransformer] = None
    if chaos_key is not None:
        chaos = ChaosTransformer(chaos_key)
        payload_blob, _orig_bits = chaos.scramble(payload_blob)
        logger.info(
            "[Chaos] Arnold Cat Map applied: %d bits → %d bits (k=%d)",
            original_bit_count, len(payload_blob) * 8, chaos.arnold_k,
        )

    # 3. Parse H.264 + 4. safety filter (runtime cacheable cover analysis)
    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    raw_safe_bits = len(safe_positions)
    ffmpeg_validated_bits: Optional[int] = None
    patchable_usable_bits: Optional[int] = None
    requested_position_bits: Optional[int] = None

    if precomputed_positions is not None:
        safe_positions = _limit_positions_per_block(
            [tuple(int(v) for v in pos) for pos in precomputed_positions],
            max_modifications_per_block=max_modifications_per_block,
        )
        requested_position_bits = len(safe_positions)
    else:
        # 4b. Chaos: Logistic Map — shuffle position order
        if chaos is not None:
            safe_positions = chaos.shuffle_positions(safe_positions)
            logger.info(
                "[Chaos] Logistic Map shuffle applied to %d positions (seed=%.6f)",
                len(safe_positions), chaos.logistic_seed,
            )

        # 4c. Optional FFmpeg validator — pre-filter positions BEFORE passing as
        # pre_validated_positions.  stego.py sets ffmpeg_validator=None whenever
        # pre_validated_positions is provided, so we must validate here instead.
        # Cap at 5× required bits to prevent hour-long loops on large position pools.
        if ffmpeg_validate:
            rec = BitstreamReconstructor()
            _vfn, _cleanup = rec.make_ffmpeg_position_validator(
                video_path, coefficients, frame_verified_data
            )
            _required = len(payload_blob) * 8
            _max_tries = max(_required * 5, 2000)
            _total_candidates = len(safe_positions)
            _validated: list = []
            _tried = 0
            for p in safe_positions:
                if len(_validated) >= _required or _tried >= _max_tries:
                    break
                _tried += 1
                if _vfn(p[0], p[1], p[2]):
                    _validated.append(p)
            _cleanup()
            logger.info(
                "[FFmpeg] %d/%d passed (tried %d/%d candidates, needed %d)",
                len(_validated), _tried, _tried, _total_candidates, _required,
            )
            safe_positions = _validated
            ffmpeg_validated_bits = len(safe_positions)

        # 4d. Keep only positions whose blocks are patchable in the original bitstream.
        safe_positions = _prune_patchable_positions(
            safe_positions,
            frame_verified_data,
            required_bits=len(payload_blob) * 8,
        )
        safe_positions = _limit_positions_per_block(
            safe_positions,
            max_modifications_per_block=max_modifications_per_block,
        )
        patchable_usable_bits = len(safe_positions)

    if ffmpeg_validated_bits is None and precomputed_positions is None:
        ffmpeg_validated_bits = len(safe_positions)
    if patchable_usable_bits is None:
        patchable_usable_bits = len(safe_positions)
    if requested_position_bits is None:
        requested_position_bits = len(safe_positions)

    # 5. Embed payload using pre-validated (and optionally chaos-shuffled) positions
    embedder = PayloadEmbedder(max_modifications_per_block=max_modifications_per_block)
    modified, bits_embedded = embedder.embed_payload(
        coefficients, payload_blob,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
        frame_verified_data=frame_verified_data,
        ffmpeg_validator=None,          # already pre-validated above
        pre_validated_positions=safe_positions,
    )

    required_bits = len(payload_blob) * 8
    if bits_embedded < required_bits:
        raise InsufficientCapacityError(
            required_bits=required_bits,
            available_bits=bits_embedded,
            stage="pre_reconstruct_embedding",
            raw_safe_bits=raw_safe_bits,
            ffmpeg_validated_bits=ffmpeg_validated_bits,
            patchable_usable_bits=patchable_usable_bits,
            requested_position_bits=requested_position_bits,
            trust_precomputed_positions=trust_precomputed_positions,
            chaos_enabled=bool(chaos is not None),
        )

    used_positions = [
        (int(mb), int(blk), int(cidx))
        for mb, blk, cidx in getattr(embedder, "last_used_safe_positions", [])
    ]

    # 6. Reconstruct stego video
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    reconstruction_context = load_or_build_reconstruction_context(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    rec2 = BitstreamReconstructor()
    reconstruction_stats = rec2.reconstruct_video(
        video_path, modified, output_path,
        max_slices=None,
        frame_verified_data=frame_verified_data,
        reconstruction_context=reconstruction_context,
    )

    if trust_precomputed_positions and precomputed_positions is not None:
        bits_embedded = len(used_positions)
        applied_position_bits = len(used_positions)
    else:
        applied_block_keys = {
            (int(mb), int(blk))
            for mb, blk in reconstruction_stats.get("applied_block_keys", [])
        }
        if applied_block_keys:
            used_positions = [
                (mb, blk, cidx)
                for mb, blk, cidx in used_positions
                if (mb, blk) in applied_block_keys
            ]
            bits_embedded = len(used_positions)
            applied_position_bits = len(used_positions)
        else:
            used_positions = []
            bits_embedded = 0
            applied_position_bits = 0

    if bits_embedded < required_bits:
        raise InsufficientCapacityError(
            required_bits=required_bits,
            available_bits=bits_embedded,
            stage="post_reconstruct_application",
            raw_safe_bits=raw_safe_bits,
            ffmpeg_validated_bits=ffmpeg_validated_bits,
            patchable_usable_bits=patchable_usable_bits,
            requested_position_bits=requested_position_bits,
            applied_position_bits=applied_position_bits,
            trust_precomputed_positions=trust_precomputed_positions,
            chaos_enabled=bool(chaos is not None),
        )

    # Save positions.json (legacy, for compatibility)
    pos_path = f"{output_path}.positions.json"
    with open(pos_path, "w", encoding="utf-8") as f:
        json.dump([[mb, blk, cidx] for mb, blk, cidx in used_positions], f, ensure_ascii=True, indent=2)

    # Save meta.json (legacy, for compatibility)
    meta_path = f"{output_path}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "bits_embedded": int(bits_embedded),
                "bits_required": int(required_bits),
                "positions_count": len(used_positions),
                "raw_safe_bits": raw_safe_bits,
                "ffmpeg_validated_bits": ffmpeg_validated_bits,
                "patchable_usable_bits": patchable_usable_bits,
                "requested_position_bits": requested_position_bits,
                "applied_position_bits": applied_position_bits,
                "chaos_enabled": bool(chaos is not None),
                "chaos_original_bits": (int(original_bit_count) if chaos is not None else None),
            },
            f,
            ensure_ascii=True,
            indent=2,
        )

    # Save versioned manifest.json
    manifest = StegoManifest(
        payload=PayloadMetadata(
            message_length=len(message),
            bits_embedded=bits_embedded,
            bits_required=required_bits,
            chaos_enabled=chaos is not None,
            chaos_original_bits=original_bit_count if chaos is not None else None,
            chaos_expansion_factor=len(payload_blob) * 8 / original_bit_count if chaos is not None else 1.0,
        ),
        embedding=EmbeddingMetadata(
            strategy="t1_sign_flip",
            max_modifications_per_block=max_modifications_per_block,
            positions_count=len(used_positions),
        ),
        video=VideoMetadata(
            file_path=video_path,
            file_hash=compute_file_hash(video_path),
            codec="h264",
            profile="baseline",
        ),
        proof=ProofMetadata(
            proof_system="groth16",
            proof_size_bytes=len(proof_bytes),
            constraint_count=bridge.get_constraint_count(),
        ),
    )
    manifest_path = f"{output_path}.manifest.json"
    manifest.save(manifest_path)
    capacity = sum(
        1 for _, _, coeffs in coefficients for v in coeffs if abs(v) == 1
    )

    return EmbedResult(
        bits_embedded=bits_embedded,
        capacity_bits=capacity,
        stream_class=stream_profile.inferred_gop_class,
        raw_safe_bits=raw_safe_bits,
        patchable_usable_bits=patchable_usable_bits,
        ffmpeg_validated_bits=ffmpeg_validated_bits,
        requested_position_bits=requested_position_bits,
        applied_position_bits=applied_position_bits,
        output_path=output_path,
        proof_dict=proof_dict,
        public_dict=public_dict,
        chaos_original_bits=original_bit_count if chaos is not None else None,
        used_positions=used_positions,
    )
