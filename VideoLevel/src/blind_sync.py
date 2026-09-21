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
import heapq
import json
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Optional

from .core.analysis_cache import (
    load_or_build_video_analysis,
)
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

# Blind extraction must be able to re-derive this policy from the stego stream.
# Indices are CAVLC zig-zag positions; index 0 is DC and low indices carry the
# most visible AC energy.  The operating path uses only the high-frequency tail.
BLIND_MIN_SIGN_COEFFICIENT_INDEX = 7


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


def build_blind_sign_candidates(
    safe_positions: list[tuple[int, int, int]],
    *,
    is_flip_patchable: Callable[[tuple[int, int, int]], bool] | None = None,
    min_coefficient_index: int = 1,
) -> list[tuple[int, int, int]]:
    """Select CAVLC-validated trailing-one sign positions for blind mode.

    The normal safety filter emits negative indices only after it verifies that
    the coefficient is a genuine CAVLC trailing-one sign flag and that a sign
    flip retains a patchable block.  Arbitrary non-zero AC coefficients do not
    have that guarantee.  Exactly one position per block preserves the blind
    one-bit-per-block schedule.
    """
    if min_coefficient_index < 1:
        raise ValueError("blind sign candidates must exclude the DC coefficient")

    selected: list[tuple[int, int, int]] = []
    seen_blocks: set[tuple[int, int]] = set()
    for mb_idx, block_idx, coeff_idx in safe_positions:
        if int(coeff_idx) >= 0:
            continue
        # ``~0`` encodes luma DC; low zig-zag indices carry the strongest image
        # energy.  Both parties apply this fixed threshold before key ordering.
        if ~int(coeff_idx) < min_coefficient_index:
            continue
        key = (int(mb_idx), int(block_idx))
        if key in seen_blocks:
            continue
        candidate = (key[0], key[1], int(coeff_idx))
        # A blind receiver cannot consult a sidecar to learn that an attempted
        # sign flip was rejected during reconstruction.  Callers may therefore
        # supply a symmetric (both-sign-states) patchability predicate and only
        # admit positions that remain representable in either payload state.
        if is_flip_patchable is not None and not is_flip_patchable(candidate):
            continue
        seen_blocks.add(key)
        selected.append(candidate)
    return selected


def select_blind_candidates_bounded(
    candidates: Iterable[tuple[int, int, int]],
    ordering_key: bytes,
    *,
    required_bits: int,
) -> list[tuple[int, int, int]]:
    """Select the HMAC-lowest candidates while retaining only ``required_bits``.

    The returned order is identical to sorting the complete candidate stream by
    the blind ordering score, but the max-heap makes storage O(required_bits).
    """
    if required_bits <= 0:
        return []
    if not ordering_key:
        raise ValueError("ordering_key must be non-empty")
    heap: list[tuple[int, tuple[int, int, int]]] = []
    for candidate in candidates:
        position = (int(candidate[0]), int(candidate[1]), int(candidate[2]))
        payload = f"{position[0]}:{position[1]}:{position[2]}".encode("ascii")
        score = int.from_bytes(hmac.new(ordering_key, payload, hashlib.sha256).digest(), "big")
        entry = (-score, position)
        if len(heap) < required_bits:
            heapq.heappush(heap, entry)
        elif score < -heap[0][0]:
            heapq.heapreplace(heap, entry)
    return [position for _score, position in sorted(heap, key=lambda entry: -entry[0])]


def select_streaming_blind_positions(
    analysis_records: Iterable[tuple],
    *,
    secret_key: bytes,
    required_bits: int,
    safety_filter: CAVLCSafetyFilter | None = None,
) -> list[tuple[int, int, int]]:
    """Select the sidecar-free sign schedule without retaining video analysis.

    Version two deliberately derives ordering from a fixed, domain-separated
    key rather than batch metadata. Candidate membership is sign-invariant, so
    an extractor can independently scan the stego stream and obtain the same
    schedule. Only the requested number of HMAC-lowest positions is retained.
    """
    if not isinstance(secret_key, bytes) or len(secret_key) != 32:
        raise ValueError("secret_key must be exactly 32 bytes")
    if required_bits <= 0:
        return []
    ordering_key = b"blind-stream-v2\x00" + secret_key
    candidates = iter_blind_sign_candidates_from_idr_analysis(
        analysis_records,
        safety_filter=safety_filter,
    )
    return select_blind_candidates_bounded(
        candidates,
        ordering_key,
        required_bits=required_bits,
    )


def iter_blind_sign_candidates_from_idr_analysis(
    analysis_records: Iterable[tuple],
    *,
    min_coefficient_index: int = BLIND_MIN_SIGN_COEFFICIENT_INDEX,
    safety_filter: CAVLCSafetyFilter | None = None,
) -> Iterator[tuple[int, int, int]]:
    """Yield validated sign candidates one IDR analysis record at a time.

    ``analysis_records`` follows ``iter_idr_luma_analysis``: each item contains
    the per-IDR coefficients, nC map, NAL lengths and verified slice data.  No
    candidate collection is retained across records, allowing the caller to
    stream candidates into a bounded selector.
    """
    if min_coefficient_index < 1:
        raise ValueError("blind sign candidates must exclude the DC coefficient")
    active_filter = safety_filter or CAVLCSafetyFilter()
    for _idr_offset, coefficients, n_c_map, nal_length_map, frame_verified_data in analysis_records:
        # The production safety filter's fast sign scanner establishes only
        # sign-offset membership.  Blind embedding additionally requires the
        # patcher's bit-exact round-trip/retroactive-boundary validation; its
        # generic validated path supplies that contract.  Keep the lighter
        # sign-only seam for injected test or specialised filters.
        if isinstance(active_filter, CAVLCSafetyFilter):
            raw_positions = active_filter.get_safe_positions(
                coefficients,
                nC_map=n_c_map,
                nal_length_map=nal_length_map,
                frame_verified_data=frame_verified_data,
            )
            seen_blocks: set[tuple[int, int]] = set()
            for candidate in raw_positions:
                mb_idx, block_idx, coefficient_idx = (int(value) for value in candidate)
                if coefficient_idx >= 0 or ~coefficient_idx < min_coefficient_index:
                    continue
                block_key = (mb_idx, block_idx)
                if block_key in seen_blocks:
                    continue
                seen_blocks.add(block_key)
                yield (mb_idx, block_idx, coefficient_idx)
            continue

        sign_positions = getattr(active_filter, "get_safe_sign_positions", None)
        if sign_positions is not None:
            seen_blocks: set[tuple[int, int]] = set()
            for candidate in sign_positions(
                coefficients,
                nC_map=n_c_map,
                nal_length_map=nal_length_map,
                frame_verified_data=frame_verified_data,
            ):
                mb_idx, block_idx, coefficient_idx = (int(value) for value in candidate)
                if ~coefficient_idx < min_coefficient_index:
                    continue
                block_key = (mb_idx, block_idx)
                if block_key in seen_blocks:
                    continue
                seen_blocks.add(block_key)
                yield (mb_idx, block_idx, coefficient_idx)
            continue
        safe_positions = active_filter.get_safe_positions(
            coefficients,
            nC_map=n_c_map,
            nal_length_map=nal_length_map,
            frame_verified_data=frame_verified_data,
        )
        candidates = build_blind_sign_candidates(
            safe_positions,
            min_coefficient_index=min_coefficient_index,
        )
        yield from _filter_flip_patchable_sign_candidates(
            candidates,
            coefficients=coefficients,
            frame_verified_data=frame_verified_data,
            required_bits=len(candidates),
        )


def _metadata_from_analysis(
    coefficients: list[tuple[int, int, list[int]]],
    frame_verified_data: dict,
    nal_length_map: dict,
    safe_positions: list[tuple[int, int, int]],
) -> tuple[BlindPublicMetadata, list[tuple[int, int, int]]]:
    """Build public metadata from a single already-parsed stream analysis."""
    stable_candidates = build_blind_stable_candidates(coefficients, nal_length_map)
    serialized = [[int(mb), int(blk), int(cidx)] for mb, blk, cidx in stable_candidates]
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


def _filter_flip_patchable_sign_candidates(
    candidates: list[tuple[int, int, int]],
    *,
    coefficients: list[tuple[int, int, list[int]]],
    frame_verified_data: dict,
    required_bits: int,
) -> list[tuple[int, int, int]]:
    """Keep sign candidates that the patcher can flip and then flip back.

    The direct CAVLC safety check validates codeword length, but a blind
    schedule also needs the bitstream patcher to accept the block in *both*
    possible sign states.  Otherwise the embedder can skip an attempted bit
    while a sidecar-free receiver has no way to remove that position from its
    deterministic schedule.

    Validation is deliberately bounded: ordered candidates are checked only
    until the requested schedule is full.  It operates entirely on the video
    being processed (cover at embed time, stego at verify time) and writes no
    sidecar or output file.
    """
    if required_bits <= 0:
        return []

    coeff_map = {(int(mb), int(blk)): list(values) for mb, blk, values in coefficients}
    idr_offsets = sorted(int(offset) for offset in frame_verified_data)
    retained: list[tuple[int, int, int]] = []

    for candidate in candidates:
        mb, blk, encoded_idx = (int(candidate[0]), int(candidate[1]), int(candidate[2]))
        if encoded_idx >= 0:
            continue
        idr_index = bisect_right(idr_offsets, mb) - 1
        if idr_index < 0:
            continue
        idr_offset = idr_offsets[idr_index]
        original_coeffs = coeff_map.get((mb, blk))
        if original_coeffs is None:
            continue
        real_idx = ~encoded_idx
        if real_idx < 0 or real_idx >= len(original_coeffs) or original_coeffs[real_idx] == 0:
            continue

        global_offsets, global_blocks, _rbsp = frame_verified_data[idr_offset]
        if global_offsets.get((mb, blk)) is None:
            continue

        # Sign-only candidates have already passed CAVLCSafetyFilter's
        # bit-length and patchability checks.  Direct sign-flag patching does
        # not re-encode a block, so constructing two whole patched NALs here is
        # unnecessary and makes the sender/receiver preflight O(N * RBSP).
        base = global_blocks.get((mb, blk))
        if base is None:
            continue
        if real_idx >= len(base) or base[real_idx] == 0:
            continue

        retained.append((mb, blk, encoded_idx))
        if len(retained) >= required_bits:
            break

    return retained


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
    """Load video analysis then derive ordered sidecar-free positions."""
    analysis = load_or_build_video_analysis(
        video_path,
        use_cache=use_analysis_cache,
        force_refresh=force_analysis_refresh,
        cache_dir=analysis_cache_dir,
    )
    return derive_blind_positions_from_analysis(
        analysis,
        secret_key=secret_key,
        required_bits=required_bits,
    )


def derive_blind_positions_from_analysis(
    analysis: tuple,
    *,
    secret_key: bytes,
    required_bits: int,
) -> tuple[list[tuple[int, int, int]], BlindPublicMetadata]:
    """Derive blind positions from one already-loaded video analysis."""
    if len(analysis) != 6:
        raise ValueError("analysis must contain the six video-analysis values")
    (
        coefficients,
        frame_verified_data,
        _nC_map,
        nal_length_map,
        _t1_override_map,
        safe_positions,
    ) = analysis
    metadata, _stable_candidates = _metadata_from_analysis(
        coefficients,
        frame_verified_data,
        nal_length_map,
        safe_positions,
    )
    seed_base = derive_seed_base(metadata)
    ordering_key = derive_ordering_key(secret_key, seed_base)

    def _score(pos: tuple[int, int, int]) -> bytes:
        payload = f"{pos[0]}:{pos[1]}:{pos[2]}".encode("ascii")
        return hmac.new(ordering_key, payload, hashlib.sha256).digest()

    ordered = sorted(
        build_blind_sign_candidates(
            safe_positions,
            min_coefficient_index=BLIND_MIN_SIGN_COEFFICIENT_INDEX,
        ),
        key=_score,
    )
    patchable = _filter_flip_patchable_sign_candidates(
        ordered,
        coefficients=coefficients,
        frame_verified_data=frame_verified_data,
        required_bits=required_bits,
    )
    return patchable, metadata
