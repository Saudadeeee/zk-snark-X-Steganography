"""
blind_sync.py - Metadata-derived blind synchronization primitives.

This module does not claim a complete blind verifier. It provides the core
building blocks for a sidecar-free synchronization architecture:

  public metadata -> seed_base
  seed_base + secret -> ordering key
  ordering key + stable candidate set -> derived positions
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from typing import Optional

from .core.analysis_cache import load_or_build_video_analysis
from .core.chaos import ChaosTransformer
from .core.stego import CAVLCSafetyFilter
from .core.stego import stable_blind_candidate_index as _stable_candidate_index

BLIND_ENVELOPE_MAGIC = b"ZKVP"
BLIND_ENVELOPE_VERSION = 1
BLIND_ENVELOPE_KIND_DATA = 1
BLIND_ENVELOPE_PREFIX_BYTES = 10
BLIND_ENVELOPE_HEADER_BYTES = 14
MAX_BLIND_PAYLOAD_BYTES = 16 * 1024 * 1024


def pack_blind_payload(payload: bytes) -> bytes:
    """Frame payload bytes with version, type, exact length, and CRC-32."""
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if len(payload) > MAX_BLIND_PAYLOAD_BYTES:
        raise ValueError("payload exceeds blind-envelope size limit")
    prefix = struct.pack(
        ">4sBBI",
        BLIND_ENVELOPE_MAGIC,
        BLIND_ENVELOPE_VERSION,
        BLIND_ENVELOPE_KIND_DATA,
        len(payload),
    )
    checksum = zlib.crc32(prefix + payload) & 0xFFFFFFFF
    return prefix + struct.pack(">I", checksum) + payload


def parse_blind_payload_header(header: bytes) -> int:
    """Validate fixed framing fields and return the declared payload length."""
    if not isinstance(header, bytes) or len(header) != BLIND_ENVELOPE_HEADER_BYTES:
        raise ValueError(f"blind payload header must be {BLIND_ENVELOPE_HEADER_BYTES} bytes")
    magic, version, kind, payload_length = struct.unpack(">4sBBI", header[:BLIND_ENVELOPE_PREFIX_BYTES])
    if magic != BLIND_ENVELOPE_MAGIC:
        raise ValueError("blind payload magic mismatch")
    if version != BLIND_ENVELOPE_VERSION:
        raise ValueError("unsupported blind payload version")
    if kind != BLIND_ENVELOPE_KIND_DATA:
        raise ValueError("unsupported blind payload kind")
    if payload_length > MAX_BLIND_PAYLOAD_BYTES:
        raise ValueError("declared blind payload exceeds size limit")
    return payload_length


def unpack_blind_payload(envelope: bytes) -> bytes:
    """Validate exact envelope length and CRC before returning payload bytes."""
    if not isinstance(envelope, bytes) or len(envelope) < BLIND_ENVELOPE_HEADER_BYTES:
        raise ValueError("blind payload envelope is truncated")
    payload_length = parse_blind_payload_header(envelope[:BLIND_ENVELOPE_HEADER_BYTES])
    expected_length = BLIND_ENVELOPE_HEADER_BYTES + payload_length
    if len(envelope) != expected_length:
        raise ValueError("blind payload envelope length mismatch")
    prefix = envelope[:BLIND_ENVELOPE_PREFIX_BYTES]
    checksum = struct.unpack(">I", envelope[BLIND_ENVELOPE_PREFIX_BYTES:BLIND_ENVELOPE_HEADER_BYTES])[0]
    payload = envelope[BLIND_ENVELOPE_HEADER_BYTES:]
    if zlib.crc32(prefix + payload) & 0xFFFFFFFF != checksum:
        raise ValueError("blind payload checksum mismatch")
    return payload


@dataclass
class BlindPublicMetadata:
    version: str
    codec: str
    profile: str
    idr_count: int
    raw_safe_bits: int
    patchable_block_count: int
    stable_candidate_count: int
    candidate_fingerprint: str
    analysis_profile: str = "full-v1"


@dataclass(frozen=True)
class BlindVideoPayloadResult:
    payload: bytes
    metadata: BlindPublicMetadata
    envelope_size_bytes: int
    carriers_used: int
    carrier_positions: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class BlindVideoEmbedResult:
    output_path: str
    metadata: BlindPublicMetadata
    payload_bytes: int
    envelope_bytes: int
    carriers_used: int
    modified_carriers: int


@dataclass
class BlindOperatingContract:
    version: str = "blind-contract-v1"
    signbit_only: bool = False
    bottom_rows: int = 0
    dedup_per_block: bool = True
    max_bits_per_idr: int = 0
    metadata_bound: bool = False
    require_bitstream_patchable: bool = False
    patchability_headroom: int = 256
    max_modifications_per_block: int = 1
    stable_carriers_only: bool = False


DEFAULT_VALIDATED_POOL_PROXY_CONTRACT = BlindOperatingContract(
    version="validated-pool-patchable-v2",
    signbit_only=False,
    bottom_rows=0,
    dedup_per_block=True,
    max_bits_per_idr=0,
    metadata_bound=False,
    require_bitstream_patchable=True,
    patchability_headroom=256,
    max_modifications_per_block=1,
)

DEFAULT_BLIND_HEADER_CONTRACT = BlindOperatingContract(
    version="blind-header-v1",
    signbit_only=True,
    bottom_rows=4,
    dedup_per_block=True,
    max_bits_per_idr=1,
    metadata_bound=False,
)


def build_blind_stable_candidates(
    coefficients: list[tuple[int, int, list[int]]],
    nal_length_map: dict,
) -> list[tuple[int, int, int]]:
    """
    Derive one stable candidate position per patchable luma block.

    This is intentionally stricter than the normal safety-filter candidate set.
    """
    safety = CAVLCSafetyFilter()
    positions: list[tuple[int, int, int]] = []
    for mb_idx, blk_idx, coeffs in coefficients:
        if blk_idx >= 16:
            continue
        bit_len = nal_length_map.get((mb_idx, blk_idx))
        if bit_len is None or bit_len <= 0:
            continue
        trailing = safety._detect_trailing_ones(coeffs)
        cidx = _stable_candidate_index(coeffs, trailing)
        if cidx is None:
            continue
        positions.append((int(mb_idx), int(blk_idx), int(cidx)))
    return positions


def _metadata_from_analysis(
    coefficients: list[tuple[int, int, list[int]]],
    frame_verified_data: dict,
    nal_length_map: dict,
    safe_positions: list[tuple[int, int, int]],
    *,
    analysis_profile: str = "full-v1",
) -> tuple[BlindPublicMetadata, list[tuple[int, int, int]]]:
    """Build blind synchronization metadata from an existing video analysis."""
    if analysis_profile == "stable-blind-v1":
        # The safety filter already chose the first rank-stable, individually
        # patchable carrier in each block. Reuse that exact set for the blind
        # fingerprint; re-deriving only the first structural candidate would
        # discard safe fallbacks and could disagree with the validated choice.
        stable_candidates = list(safe_positions)
    else:
        stable_candidates = build_blind_stable_candidates(coefficients, nal_length_map)
    serialized = [[int(mb), int(blk), int(cidx)] for mb, blk, cidx in stable_candidates]
    candidate_fingerprint = hashlib.sha256(
        json.dumps(serialized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    metadata = BlindPublicMetadata(
        version=(
            "blind-sync-stable-v1"
            if analysis_profile == "stable-blind-v1"
            else "blind-sync-v1"
        ),
        codec="h264",
        profile="baseline-cavlc",
        idr_count=len(frame_verified_data),
        raw_safe_bits=len(safe_positions),
        patchable_block_count=sum(
            1 for bit_len in nal_length_map.values() if bit_len is not None and bit_len > 0
        ),
        stable_candidate_count=len(stable_candidates),
        candidate_fingerprint=candidate_fingerprint,
        analysis_profile=analysis_profile,
    )
    return metadata, stable_candidates


def extract_public_metadata(
    video_path: str,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[BlindPublicMetadata, list[tuple[int, int, int]]]:
    """
    Extract public metadata and blind-stable candidate positions from a video.
    """
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )

    return _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
    )


def derive_seed_base(metadata: BlindPublicMetadata) -> bytes:
    payload = json.dumps(
        {
            "version": metadata.version,
            "codec": metadata.codec,
            "profile": metadata.profile,
            "idr_count": metadata.idr_count,
            "raw_safe_bits": metadata.raw_safe_bits,
            "patchable_block_count": metadata.patchable_block_count,
            "stable_candidate_count": metadata.stable_candidate_count,
            "candidate_fingerprint": metadata.candidate_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def derive_ordering_key(secret_key: bytes, seed_base: bytes) -> bytes:
    return hmac.new(secret_key, seed_base + b"|blind-order-v1", hashlib.sha256).digest()


def _dedup_per_block(
    positions: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    seen: set[tuple[int, int]] = set()
    deduped: list[tuple[int, int, int]] = []
    for mb, blk, cidx in positions:
        key = (int(mb), int(blk))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((int(mb), int(blk), int(cidx)))
    return deduped


def _cap_per_idr(
    positions: list[tuple[int, int, int]],
    *,
    cif_mb_count: int,
    max_bits_per_idr: int,
) -> list[tuple[int, int, int]]:
    if max_bits_per_idr <= 0:
        return list(positions)
    counts: dict[int, int] = {}
    limited: list[tuple[int, int, int]] = []
    for pos in positions:
        frame_idx = int(pos[0]) // cif_mb_count
        used = counts.get(frame_idx, 0)
        if used >= max_bits_per_idr:
            continue
        limited.append((int(pos[0]), int(pos[1]), int(pos[2])))
        counts[frame_idx] = used + 1
    return limited


def _filter_signbit_positions(
    positions: list[tuple[int, int, int]],
) -> list[tuple[int, int, int]]:
    return [pos for pos in positions if int(pos[2]) < 0]


def _filter_bottom_zone(
    positions: list[tuple[int, int, int]],
    *,
    cif_mb_count: int,
    cif_mb_width: int = 22,
    bottom_rows: int = 4,
) -> list[tuple[int, int, int]]:
    if bottom_rows <= 0:
        return list(positions)
    mb_height = max(1, cif_mb_count // cif_mb_width)
    bottom_row_start = max(0, mb_height - bottom_rows)
    filtered = []
    for pos in positions:
        local_mb = int(pos[0]) % cif_mb_count
        row = local_mb // cif_mb_width
        if row >= bottom_row_start:
            filtered.append((int(pos[0]), int(pos[1]), int(pos[2])))
    return filtered


def derive_blind_positions_chaos_dedup(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
    *,
    metadata_bound: bool = False,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Derive positions from the same safe-position universe used by the cover path,
    then apply chaos-like ordering and per-block deduplication.

    This is closer to the current operating-point generation than the stricter
    blind-stable single-candidate prototype.
    """
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
    )
    seed_base = derive_seed_base(metadata)
    ordering_secret = derive_ordering_key(sync_key, seed_base) if metadata_bound else bytes(sync_key)
    ordered = ChaosTransformer(ordering_secret).shuffle_positions(list(safe_positions))
    deduped = _dedup_per_block(ordered)
    return deduped[:required_bits], metadata


def derive_blind_positions_operating_like(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
    *,
    cif_mb_count: int = 396,
    max_bits_per_idr: int = 5,
    metadata_bound: bool = False,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Approximate the SEC1 operating-position path without external sidecars.

    Steps:
      1. derive the same safe-position universe
      2. chaos-style shuffle
      3. dedup per block
      4. enforce a deterministic per-IDR cap
      5. take the required prefix
    """
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
    )
    seed_base = derive_seed_base(metadata)
    ordering_secret = derive_ordering_key(sync_key, seed_base) if metadata_bound else bytes(sync_key)
    ordered = ChaosTransformer(ordering_secret).shuffle_positions(list(safe_positions))
    deduped = _dedup_per_block(ordered)
    capped = _cap_per_idr(
        deduped,
        cif_mb_count=cif_mb_count,
        max_bits_per_idr=max_bits_per_idr,
    )
    return capped[:required_bits], metadata


def derive_blind_positions_operating_signbit_like(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
    *,
    cif_mb_count: int = 396,
    max_bits_per_idr: int = 5,
    bottom_rows: int = 4,
    metadata_bound: bool = False,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Bias the blind candidate universe toward the current SEC1 operating path:
      safe positions -> sign-bit only -> bottom-zone -> chaos ordering ->
      dedup per block -> per-IDR cap
    """
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
    )
    seed_base = derive_seed_base(metadata)
    ordering_secret = derive_ordering_key(sync_key, seed_base) if metadata_bound else bytes(sync_key)
    filtered = _filter_signbit_positions(list(safe_positions))
    filtered = _filter_bottom_zone(
        filtered,
        cif_mb_count=cif_mb_count,
        bottom_rows=bottom_rows,
    )
    ordered = ChaosTransformer(ordering_secret).shuffle_positions(list(filtered))
    deduped = _dedup_per_block(ordered)
    capped = _cap_per_idr(
        deduped,
        cif_mb_count=cif_mb_count,
        max_bits_per_idr=max_bits_per_idr,
    )
    return capped[:required_bits], metadata


def derive_blind_positions_operating_contract(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
    contract: BlindOperatingContract,
    *,
    cif_mb_count: int = 396,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Generic operating-contract-derived blind position generator.
    """
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
        stable_blind_only=(
            contract.stable_carriers_only and not contract.signbit_only
        ),
    )
    stable_profile = contract.stable_carriers_only and not contract.signbit_only
    metadata, _stable_candidates = _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
        analysis_profile="stable-blind-v1" if stable_profile else "full-v1",
    )
    seed_base = derive_seed_base(metadata)
    ordering_secret = derive_ordering_key(sync_key, seed_base) if contract.metadata_bound else bytes(sync_key)

    if contract.stable_carriers_only:
        safe_set = set(safe_positions)
        candidates = [pos for pos in _stable_candidates if pos in safe_set]
    else:
        candidates = list(safe_positions)
    if contract.signbit_only:
        candidates = _filter_signbit_positions(candidates)
    if contract.bottom_rows > 0:
        candidates = _filter_bottom_zone(
            candidates,
            cif_mb_count=cif_mb_count,
            bottom_rows=contract.bottom_rows,
        )

    ordered = ChaosTransformer(ordering_secret).shuffle_positions(candidates)
    if contract.dedup_per_block:
        ordered = _dedup_per_block(ordered)
    if contract.require_bitstream_patchable:
        if contract.patchability_headroom < 0:
            raise ValueError("patchability_headroom must be non-negative")
        if contract.max_modifications_per_block < 1:
            raise ValueError("max_modifications_per_block must be positive")
    if contract.require_bitstream_patchable and not stable_profile:
        from .embedder import _prune_patchable_positions

        patchable_target = max(
            required_bits + contract.patchability_headroom,
            int(required_bits * 1.30),
        )
        ordered = _prune_patchable_positions(
            ordered,
            frame_verified_data,
            required_bits=patchable_target,
            max_modifications_per_block=contract.max_modifications_per_block,
        )
    if contract.max_bits_per_idr > 0:
        ordered = _cap_per_idr(
            ordered,
            cif_mb_count=cif_mb_count,
            max_bits_per_idr=contract.max_bits_per_idr,
        )
    return ordered[:required_bits], metadata


def embed_blind_video_payload(
    cover_video_path: str,
    output_video_path: str,
    payload: bytes,
    sync_key: bytes,
    contract: BlindOperatingContract,
) -> BlindVideoEmbedResult:
    """Embed a self-framed payload into H.264 residuals without sidecar output.

    This experimental channel API does not create or assert a ZKP. The caller
    supplies already generated proof bytes and remains responsible for their
    cryptographic meaning and public-statement binding.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    if not isinstance(sync_key, bytes) or not sync_key:
        raise ValueError("sync_key must be non-empty bytes")
    if not contract.stable_carriers_only or not contract.require_bitstream_patchable:
        raise ValueError("sidecar-free embedding requires stable, patchability-checked carriers")
    if contract.max_modifications_per_block != 1:
        raise ValueError("stable-carrier embedding requires one modification per block")
    if os.path.exists(output_video_path):
        raise FileExistsError(f"Output video already exists: {output_video_path}")
    if not os.path.isfile(cover_video_path):
        raise FileNotFoundError(f"Cover video not found: {cover_video_path}")
    output_parent = os.path.dirname(os.path.abspath(output_video_path))
    if not os.path.isdir(output_parent):
        raise FileNotFoundError(f"Output directory not found: {output_parent}")

    from .bitstream.bitstream_ops import BitstreamReconstructor
    from .core.stego import PayloadEmbedder
    from .embedder import _strict_validate_h264_decode

    envelope = pack_blind_payload(payload)
    required_bits = len(envelope) * 8
    analysis = load_or_build_video_analysis(
        cover_video_path,
        use_cache=True,
        stable_blind_only=True,
    )
    coefficients, frame_data, n_c_map, nal_lengths, t1_overrides = analysis[:5]
    positions, metadata = derive_blind_positions_operating_contract(
        cover_video_path,
        sync_key,
        required_bits,
        contract,
        use_analysis_cache=True,
    )
    if len(positions) != required_bits:
        raise ValueError(
            f"insufficient stable patchable capacity: need {required_bits} carriers, got {len(positions)}"
        )

    embedder = PayloadEmbedder(
        max_modifications_per_block=contract.max_modifications_per_block
    )
    modified, embedded_bits = embedder.embed_payload(
        coefficients,
        envelope,
        nC_map=n_c_map,
        nal_length_map=nal_lengths,
        t1_override_map=t1_overrides,
        frame_verified_data=frame_data,
        pre_validated_positions=positions,
    )
    if embedded_bits != required_bits:
        raise RuntimeError(f"short embed: wrote {embedded_bits} of {required_bits} bits")

    suffix = os.path.splitext(output_video_path)[1] or ".h264"
    fd, candidate_path = tempfile.mkstemp(
        prefix=".zkstego-candidate-", suffix=suffix, dir=output_parent
    )
    os.close(fd)
    os.unlink(candidate_path)
    try:
        stats = BitstreamReconstructor().reconstruct_video(
            cover_video_path,
            modified,
            candidate_path,
            max_slices=None,
            frame_verified_data=frame_data,
        )
        if not stats.get("success") or not os.path.isfile(candidate_path):
            raise RuntimeError(f"H.264 reconstruction failed: {stats}")
        expected_blocks = {
            (int(mb), int(block))
            for mb, block, _coefficients in modified
        }
        applied_blocks = {
            (int(mb), int(block))
            for mb, block in stats.get("applied_block_keys", [])
        }
        missing_blocks = expected_blocks - applied_blocks
        if missing_blocks:
            preview = sorted(missing_blocks)[:8]
            skipped_reasons = stats.get("skipped_block_reasons", {})
            reason_preview = {
                key: skipped_reasons.get(key, "no_skip_reason_reported")
                for key in preview
            }
            offset_preview = {}
            for block_key in preview:
                offset_data = next(
                    (
                        offsets.get(block_key)
                        for offsets, _blocks, _rbsp in frame_data.values()
                        if block_key in offsets
                    ),
                    None,
                )
                if offset_data is not None:
                    offset_preview[block_key] = {
                        field: offset_data.get(field)
                        for field in ("nC", "validated_nC", "start_bit", "end_bit", "bit_length")
                    }
            raise RuntimeError(
                "reconstruction did not apply all embedded carrier blocks; "
                f"{len(missing_blocks)} missing, first={reason_preview}, "
                f"verified_offsets={offset_preview}"
            )
        _strict_validate_h264_decode(candidate_path)
        os.rename(candidate_path, output_video_path)
    except Exception:
        if os.path.exists(candidate_path):
            os.unlink(candidate_path)
        raise

    return BlindVideoEmbedResult(
        output_path=output_video_path,
        metadata=metadata,
        payload_bytes=len(payload),
        envelope_bytes=len(envelope),
        carriers_used=embedded_bits,
        modified_carriers=len(embedder.last_modified_safe_positions),
    )


def extract_blind_video_payload(
    video_path: str,
    sync_key: bytes,
    contract: BlindOperatingContract,
) -> BlindVideoPayloadResult:
    """Extract a self-framed payload using only a stego video and verifier config.

    This experimental payload-channel API does not verify a ZKP. The caller
    must pass the returned bytes to the selected proof verifier.
    """
    if not isinstance(sync_key, bytes) or not sync_key:
        raise ValueError("sync_key must be non-empty bytes")
    if not contract.stable_carriers_only:
        raise ValueError("video-only extraction requires stable_carriers_only=True")

    from .core.pipeline import _extract_bits_from_decoded_analysis

    analysis = load_or_build_video_analysis(
        video_path,
        use_cache=True,
        stable_blind_only=True,
    )
    frame_verified_data = analysis[1]
    n_c_map = analysis[2]

    header_bits = BLIND_ENVELOPE_HEADER_BYTES * 8
    header_positions, metadata = derive_blind_positions_operating_contract(
        video_path,
        sync_key,
        header_bits,
        contract,
        use_analysis_cache=True,
    )
    if len(header_positions) != header_bits:
        raise ValueError("video does not contain enough stable carriers for the envelope header")
    header = _extract_bits_from_decoded_analysis(
        stego_video_path=video_path,
        embed_safe_positions=header_positions,
        frame_verified_data=frame_verified_data,
        nC_map=n_c_map,
        payload_bits=header_bits,
        max_modifications_per_block=contract.max_modifications_per_block,
    )
    payload_length = parse_blind_payload_header(header)
    envelope_size = BLIND_ENVELOPE_HEADER_BYTES + payload_length
    envelope_bits = envelope_size * 8

    positions, _ = derive_blind_positions_operating_contract(
        video_path,
        sync_key,
        envelope_bits,
        contract,
        use_analysis_cache=True,
    )
    if len(positions) != envelope_bits:
        raise ValueError("video does not contain enough stable carriers for the declared payload")
    envelope = _extract_bits_from_decoded_analysis(
        stego_video_path=video_path,
        embed_safe_positions=positions,
        frame_verified_data=frame_verified_data,
        nC_map=n_c_map,
        payload_bits=envelope_bits,
        max_modifications_per_block=contract.max_modifications_per_block,
    )
    payload = unpack_blind_payload(envelope)
    return BlindVideoPayloadResult(
        payload=payload,
        metadata=metadata,
        envelope_size_bytes=envelope_size,
        carriers_used=envelope_bits,
        carrier_positions=tuple(positions),
    )


def derive_blind_positions_validated_pool_proxy(
    video_path: str,
    sync_key: bytes,
    required_bits: int,
    *,
    cif_mb_count: int = 396,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Best current bridge to the SEC1 validated-pool ordering.
    """
    return derive_blind_positions_operating_contract(
        video_path,
        sync_key,
        required_bits=required_bits,
        contract=DEFAULT_VALIDATED_POOL_PROXY_CONTRACT,
        cif_mb_count=cif_mb_count,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )


def derive_blind_header_positions(
    video_path: str,
    sync_key: bytes,
    header_bits: int,
    *,
    cif_mb_count: int = 396,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    return derive_blind_positions_operating_contract(
        video_path,
        sync_key,
        required_bits=header_bits,
        contract=DEFAULT_BLIND_HEADER_CONTRACT,
        cif_mb_count=cif_mb_count,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )


def derive_blind_body_positions(
    video_path: str,
    sync_key: bytes,
    body_bits: int,
    *,
    header_positions: list[tuple[int, int, int]] | None = None,
    cif_mb_count: int = 396,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    positions, metadata = derive_blind_positions_validated_pool_proxy(
        video_path,
        sync_key,
        required_bits=(body_bits + len(header_positions or [])),
        cif_mb_count=cif_mb_count,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )
    if not header_positions:
        return positions[:body_bits], metadata
    blocked = {(int(mb), int(blk)) for mb, blk, _ in header_positions}
    filtered = [pos for pos in positions if (int(pos[0]), int(pos[1])) not in blocked]
    return filtered[:body_bits], metadata


def derive_blind_positions(
    video_path: str,
    secret_key: bytes,
    required_bits: int,
    *,
    use_analysis_cache: bool = True,
    force_analysis_refresh: bool = False,
    analysis_cache_dir: Optional[str] = None,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """
    Derive ordered positions from stego-visible metadata and a secret key.
    """
    metadata, stable_candidates = extract_public_metadata(
        video_path,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )
    seed_base = derive_seed_base(metadata)
    ordering_key = derive_ordering_key(secret_key, seed_base)

    def _score(pos: tuple[int, int, int]) -> bytes:
        payload = f"{pos[0]}:{pos[1]}:{pos[2]}".encode("ascii")
        return hmac.new(ordering_key, payload, hashlib.sha256).digest()

    ordered = sorted(stable_candidates, key=_score)
    return ordered[:required_bits], metadata
