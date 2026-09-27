"""Canonical coefficient transformations for H.264 carrier commitments.

This module only normalizes carrier coefficients. It does not by itself
define a complete video commitment or prove that carrier positions came from
an authenticated source; callers must bind the ordered positions separately.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Sequence
from pathlib import Path


CoefficientBlock = tuple[int, int, Sequence[int]]
CarrierPosition = tuple[int, int, int]
ModifiedBlock = tuple[int, int, list[int]]


def canonicalize_carrier_coefficients(
    coefficients: Sequence[CoefficientBlock],
    carrier_positions: Sequence[CarrierPosition],
) -> list[ModifiedBlock]:
    """Return only coefficient blocks changed by canonicalizing carriers.

    Non-negative carrier indexes identify magnitude-LSB carriers. Their
    magnitude is rounded down to the nearest even value while preserving its
    sign; a unit coefficient therefore canonicalizes to zero. Negative
    indexes encode trailing-one sign carriers using ``~index`` and normalize
    to positive one. The supplied coefficient structures are never mutated.

    The returned block tuples can be passed directly to
    ``BitstreamReconstructor.reconstruct_video``. Callers still need the
    original frame/parser context to produce a canonicalized bitstream.
    """
    coefficient_lookup: dict[tuple[int, int], Sequence[int]] = {}
    for item in coefficients:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("coefficient entries must be (macroblock, block, levels)")
        macroblock, block, levels = item
        if (
            isinstance(macroblock, bool)
            or not isinstance(macroblock, int)
            or isinstance(block, bool)
            or not isinstance(block, int)
            or not isinstance(levels, Sequence)
        ):
            raise ValueError("coefficient entry has invalid indexes or levels")
        key = (macroblock, block)
        if key in coefficient_lookup:
            raise ValueError(f"duplicate coefficient block: {key}")
        coefficient_lookup[key] = levels

    normalized_by_block: dict[tuple[int, int], list[int]] = {}
    seen_carriers: set[tuple[int, int, int]] = set()
    for item in carrier_positions:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("carrier positions must be (macroblock, block, coefficient)")
        macroblock, block, carrier_index = item
        if (
            isinstance(macroblock, bool)
            or not isinstance(macroblock, int)
            or isinstance(block, bool)
            or not isinstance(block, int)
            or isinstance(carrier_index, bool)
            or not isinstance(carrier_index, int)
        ):
            raise ValueError("carrier position indexes must be integers")
        position = (macroblock, block, carrier_index)
        if position in seen_carriers:
            raise ValueError(f"duplicate carrier position: {position}")
        seen_carriers.add(position)

        key = (macroblock, block)
        levels = coefficient_lookup.get(key)
        if levels is None:
            raise ValueError(f"unknown coefficient block: {key}")
        coefficient_index = ~carrier_index if carrier_index < 0 else carrier_index
        if not 0 <= coefficient_index < len(levels):
            raise ValueError(f"carrier coefficient index is out of range: {position}")

        value = levels[coefficient_index]
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            raise ValueError(f"carrier coefficient must be a non-zero integer: {position}")
        if carrier_index < 0:
            if abs(value) != 1:
                raise ValueError(f"sign carrier must be a trailing one: {position}")
            canonical_value = 1
        else:
            magnitude = abs(value) & ~1
            if magnitude == 0:
                magnitude = 2
            canonical_value = magnitude if value > 0 else -magnitude

        if canonical_value == value:
            continue
        normalized = normalized_by_block.get(key)
        if normalized is None:
            normalized = list(levels)
            normalized_by_block[key] = normalized
        normalized[coefficient_index] = canonical_value

    return [
        (macroblock, block, levels)
        for (macroblock, block), levels in sorted(normalized_by_block.items())
    ]


def canonical_video_sha256(
    video_path: str | Path,
    carrier_positions: Sequence[CarrierPosition],
) -> str:
    """Hash the H.264 byte stream after normalizing the specified carriers.

    Carrier locations must be supplied in the same global macroblock/block
    coordinate system used by the embedder. The source video is never
    modified. This function performs a full H.264 analysis and CAVLC
    reconstruction when normalization changes coefficients, so it is
    intentionally an offline commitment operation rather than a per-frame
    real-time primitive.
    """
    source = Path(video_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("video_path must identify a regular file")

    def digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    if not carrier_positions:
        return digest_file(source)

    from .bitstream.bitstream_ops import BitstreamReconstructor
    from .core.analysis_cache import (
        load_or_build_reconstruction_context,
        load_or_build_video_analysis,
    )

    coefficients, frame_data, _, _, _, _ = load_or_build_video_analysis(
        str(source), use_cache=True
    )
    modifications = canonicalize_carrier_coefficients(coefficients, carrier_positions)
    if not modifications:
        return digest_file(source)

    context = load_or_build_reconstruction_context(str(source), use_cache=True)
    reconstructor = BitstreamReconstructor()
    with tempfile.TemporaryDirectory(prefix="zkstego-canonical-h264-") as temp_dir:
        canonical_path = Path(temp_dir) / "canonical.h264"
        result = reconstructor.reconstruct_video(
            str(source),
            modifications,
            str(canonical_path),
            max_slices=None,
            frame_verified_data=frame_data,
            reconstruction_context=context,
        )
        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError("H.264 reconstruction failed during canonicalization")
        if not canonical_path.is_file() or canonical_path.stat().st_size == 0:
            raise RuntimeError("H.264 canonicalization produced no output stream")
        if not isinstance(result, dict) or not isinstance(result.get("applied_block_keys"), list):
            raise RuntimeError("H.264 reconstruction omitted applied-block evidence")
        expected_blocks = {(macroblock, block) for macroblock, block, _ in modifications}
        try:
            applied_blocks = {
                (int(key[0]), int(key[1]))
                for key in result["applied_block_keys"]
                if isinstance(key, (tuple, list)) and len(key) == 2
            }
        except (TypeError, ValueError, IndexError) as error:
            raise RuntimeError("H.264 reconstruction returned malformed applied-block evidence") from error
        if expected_blocks != applied_blocks:
            raise RuntimeError("H.264 reconstruction did not apply exactly the carrier blocks")
        return digest_file(canonical_path)
