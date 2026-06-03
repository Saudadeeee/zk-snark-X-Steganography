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
from dataclasses import dataclass
from typing import Optional

from .core.analysis_cache import load_or_build_video_analysis
from .core.chaos import ChaosTransformer
from .core.stego import CAVLCSafetyFilter


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


@dataclass
class BlindOperatingContract:
    version: str = "blind-contract-v1"
    signbit_only: bool = False
    bottom_rows: int = 0
    dedup_per_block: bool = True
    max_bits_per_idr: int = 0
    metadata_bound: bool = False


DEFAULT_VALIDATED_POOL_PROXY_CONTRACT = BlindOperatingContract(
    version="validated-pool-proxy-v1",
    signbit_only=False,
    bottom_rows=0,
    dedup_per_block=True,
    max_bits_per_idr=0,
    metadata_bound=False,
)

DEFAULT_BLIND_HEADER_CONTRACT = BlindOperatingContract(
    version="blind-header-v1",
    signbit_only=True,
    bottom_rows=4,
    dedup_per_block=True,
    max_bits_per_idr=1,
    metadata_bound=False,
)


def _stable_candidate_index(coeffs: list[int], trailing_positions: set[int]) -> Optional[int]:
    """
    Pick a coefficient index using properties that are more stable than LSB/sign.

    Priority:
    1. first AC coefficient with abs >= 2 and not a trailing-one slot
    2. first non-zero AC coefficient not in trailing-one slots
    """
    for idx in range(1, len(coeffs)):
        if coeffs[idx] != 0 and idx not in trailing_positions and abs(coeffs[idx]) >= 2:
            return idx
    for idx in range(1, len(coeffs)):
        if coeffs[idx] != 0 and idx not in trailing_positions:
            return idx
    return None


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

    stable_candidates = build_blind_stable_candidates(coefficients, nal_length_map)
    serialized = [
        [int(mb), int(blk), int(cidx)]
        for mb, blk, cidx in stable_candidates
    ]
    candidate_fingerprint = hashlib.sha256(
        json.dumps(serialized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()

    metadata = BlindPublicMetadata(
        version="blind-sync-v1",
        codec="h264",
        profile="baseline-cavlc",
        idr_count=len(frame_verified_data),
        raw_safe_bits=len(safe_positions),
        patchable_block_count=sum(1 for bit_len in nal_length_map.values() if bit_len is not None and bit_len > 0),
        stable_candidate_count=len(stable_candidates),
        candidate_fingerprint=candidate_fingerprint,
    )
    return metadata, stable_candidates


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
        _coefficients,
        frame_verified_data,
        _nC_map,
        _nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = extract_public_metadata(
        video_path,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
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
        _coefficients,
        _frame_verified_data,
        _nC_map,
        _nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = extract_public_metadata(
        video_path,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
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
        _coefficients,
        _frame_verified_data,
        _nC_map,
        _nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = extract_public_metadata(
        video_path,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
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
        _coefficients,
        _frame_verified_data,
        _nC_map,
        _nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    metadata, _stable_candidates = extract_public_metadata(
        video_path,
        use_analysis_cache=use_analysis_cache,
        force_analysis_refresh=force_analysis_refresh,
        analysis_cache_dir=analysis_cache_dir,
    )
    seed_base = derive_seed_base(metadata)
    ordering_secret = derive_ordering_key(sync_key, seed_base) if contract.metadata_bound else bytes(sync_key)

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
    if contract.max_bits_per_idr > 0:
        ordered = _cap_per_idr(
            ordered,
            cif_mb_count=cif_mb_count,
            max_bits_per_idr=contract.max_bits_per_idr,
        )
    return ordered[:required_bits], metadata


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
