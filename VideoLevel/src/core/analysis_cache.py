"""Process-local cache for expensive original-video analysis.

The previous cache persisted Python pickle objects. A cache directory is often
shared with tooling or restored from a previous run, so deserialising it made a
local-file write primitive into arbitrary code execution. Analysis values now
remain in memory for the lifetime of the trusted process only.

``cache_dir`` is retained as a deprecated API argument for compatibility but
is intentionally ignored. Callers that need cross-process caching must store
their own validated, non-executable representation.
"""

from __future__ import annotations

import hashlib
import threading
import warnings
from pathlib import Path
from typing import Any

from ..bitstream.bitstream_ops import BitstreamReconstructor
from ..bitstream.h264 import H264BitstreamParser
from .pipeline import extract_all_idr_blocks
from .stego import CAVLCSafetyFilter

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_SCHEMA_VERSION = 2

_LOCK = threading.RLock()
_VIDEO_ANALYSIS_CACHE: dict[str, tuple[dict[str, Any], tuple]] = {}
_RECONSTRUCTION_CONTEXT_CACHE: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
# SHA-256 of the exact bytes each resident analysis was built from (only
# recorded when the file was byte-identical before and after parsing).
_CONTENT_DIGESTS: dict[str, str] = {}
# Key of the one resident analysis a caller marked as unmodified and reusable
# for a different path holding byte-identical content (see
# ``park_video_analysis_for_content_reuse``).
_PARKED: dict[str, str | None] = {"key": None}


def _cache_key(video_path: str | Path) -> str:
    return str(Path(video_path).resolve())


def _code_fingerprint() -> dict[str, int | str]:
    files = [
        ROOT / "src" / "core" / "analysis_cache.py",
        ROOT / "src" / "core" / "pipeline.py",
        ROOT / "src" / "core" / "parallel_analysis.py",
        ROOT / "src" / "core" / "stego.py",
        ROOT / "src" / "bitstream" / "h264.py",
        ROOT / "src" / "bitstream" / "bitstream_ops.py",
    ]
    fingerprint: dict[str, int | str] = {"schema": CACHE_SCHEMA_VERSION}
    for file_path in files:
        key = file_path.relative_to(ROOT).as_posix()
        try:
            fingerprint[key] = int(file_path.stat().st_mtime_ns)
        except OSError:
            fingerprint[key] = "missing"
    return fingerprint


def _video_fingerprint(video_path: str | Path) -> dict[str, Any]:
    path = Path(video_path)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "code": _code_fingerprint(),
    }


def _warn_legacy_cache_dir(cache_dir: str | Path | None) -> None:
    if cache_dir is not None:
        warnings.warn(
            "analysis_cache_dir is ignored: persistent pickle caches were removed for safety.",
            DeprecationWarning,
            stacklevel=3,
        )


def _evict_other_cached_videos(active_key: str | None) -> None:
    """Keep at most one video's large analysis resident in this process.

    Pass ``None`` before rebuilding to release stale entries for the same path
    too. Call while holding ``_LOCK``. A caller that already received an
    analysis keeps its own references, so removing a cache entry does not
    mutate any in-flight operation; it only releases data no longer referenced
    elsewhere.
    """
    for cache in (_VIDEO_ANALYSIS_CACHE, _RECONSTRUCTION_CONTEXT_CACHE, _CONTENT_DIGESTS):
        for cached_key in tuple(cache):
            if active_key is None or cached_key != active_key:
                cache.pop(cached_key, None)
    if _PARKED["key"] is not None and _PARKED["key"] != active_key:
        _PARKED["key"] = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def park_video_analysis_for_content_reuse() -> bool:
    """Keep the single resident analysis for one reuse by identical content.

    A caller that has only *read* the resident analysis (never mutated it)
    may park it instead of clearing the cache. The next analysis request for
    another path then reuses it if that file has the same SHA-256, size,
    analysis profile and code fingerprint, which yields exactly the analysis a
    fresh build would produce. Any other request evicts it as usual, so at
    most one analysis stays resident. Returns whether an entry was parked;
    otherwise the cache is cleared.
    """
    with _LOCK:
        keys = list(_VIDEO_ANALYSIS_CACHE)
        if len(keys) == 1 and keys[0] in _CONTENT_DIGESTS and keys[0] in _RECONSTRUCTION_CONTEXT_CACHE:
            _evict_other_cached_videos(keys[0])
            _PARKED["key"] = keys[0]
            return True
        _evict_other_cached_videos(None)
        return False


def _adopt_parked_analysis(
    path: Path,
    key: str,
    fingerprint: dict[str, Any],
    video_fingerprint: dict[str, Any],
) -> tuple | None:
    """Re-key the parked analysis to ``path`` if its bytes are identical."""
    parked_key = _PARKED["key"]
    _PARKED["key"] = None
    if parked_key is None or parked_key == key:
        return None
    cached = _VIDEO_ANALYSIS_CACHE.get(parked_key)
    context = _RECONSTRUCTION_CONTEXT_CACHE.get(parked_key)
    digest = _CONTENT_DIGESTS.get(parked_key)
    if cached is None or context is None or digest is None:
        return None
    parked_fingerprint, data = cached
    if any(
        parked_fingerprint.get(field) != fingerprint.get(field)
        for field in ("size", "code", "analysis_profile")
    ):
        return None
    try:
        if _sha256_file(path) != digest:
            return None
    except OSError:
        return None
    _evict_other_cached_videos(parked_key)
    for cache in (_VIDEO_ANALYSIS_CACHE, _RECONSTRUCTION_CONTEXT_CACHE, _CONTENT_DIGESTS):
        cache.pop(parked_key, None)
    _VIDEO_ANALYSIS_CACHE[key] = (fingerprint, data)
    _RECONSTRUCTION_CONTEXT_CACHE[key] = (video_fingerprint, context[1])
    _CONTENT_DIGESTS[key] = digest
    return data


def _build_reconstruction_context(
    video_path: str | Path,
    parser: H264BitstreamParser | None = None,
) -> dict[str, Any]:
    path = Path(video_path)
    if parser is None:
        parser = H264BitstreamParser(str(path))
        parser.parse()

    reconstructor = BitstreamReconstructor()
    sps = None
    pps = None
    for nal in parser.nal_units:
        if int(nal.nal_unit_type) == 7:
            try:
                sps = reconstructor._parse_sps_from_nal(nal)
            except (ValueError, IndexError, EOFError):
                continue
        elif int(nal.nal_unit_type) == 8:
            try:
                pps = reconstructor._parse_pps_from_nal(nal)
            except (ValueError, IndexError, EOFError):
                continue

    mb_count_per_slice = (
        (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
        if sps is not None
        else 264
    )
    return {
        "parser": parser,
        "nal_units": parser.nal_units,
        "sps": sps,
        "pps": pps,
        "mb_count_per_slice": mb_count_per_slice,
    }


_REFERENCE_BUILD_RECONSTRUCTION_CONTEXT = _build_reconstruction_context
_REFERENCE_PARSER = H264BitstreamParser
_REFERENCE_RECONSTRUCTOR = BitstreamReconstructor


def load_or_build_video_analysis(
    video_path: str | Path,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = None,
    stable_blind_only: bool = False,
    signbit_only: bool = False,
) -> tuple:
    """Return trusted analysis, optionally validating only blind-stable carriers.

    The stable profile still runs the exact CAVLC patchability, bit-length, and
    forward-decode checks; it avoids evaluating unrelated carrier positions.
    """
    _warn_legacy_cache_dir(cache_dir)
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    key = _cache_key(path)
    video_fingerprint = _video_fingerprint(path)
    fingerprint = {
        **video_fingerprint,
        "analysis_profile": (
            "stable-blind-v1" if stable_blind_only else "signbit-v1" if signbit_only else "full-v1"
        ),
    }
    if stable_blind_only and signbit_only:
        raise ValueError("stable_blind_only and signbit_only are mutually exclusive")
    with _LOCK:
        cached = _VIDEO_ANALYSIS_CACHE.get(key)
        if use_cache and not force_refresh and cached and cached[0] == fingerprint:
            return cached[1]
        if use_cache and not force_refresh:
            adopted = _adopt_parked_analysis(path, key, fingerprint, video_fingerprint)
            if adopted is not None:
                return adopted
        _evict_other_cached_videos(None)

    content_digest = _sha256_file(path) if use_cache else None
    parser = H264BitstreamParser(str(path))
    parser.parse()
    data = _try_parallel_analysis(
        path, parser, stable_blind_only=stable_blind_only, signbit_only=signbit_only
    )
    if data is not None:
        data, context = data
    else:
        data, context = _build_serial_analysis(
            path, parser, stable_blind_only=stable_blind_only, signbit_only=signbit_only
        )

    if use_cache:
        with _LOCK:
            _evict_other_cached_videos(key)
            _VIDEO_ANALYSIS_CACHE[key] = (fingerprint, data)
            _RECONSTRUCTION_CONTEXT_CACHE[key] = (video_fingerprint, context)
            # Content reuse is only offered when the analysed file did not
            # change while it was being parsed.
            _CONTENT_DIGESTS.pop(key, None)
            try:
                unchanged = content_digest == _sha256_file(path)
            except OSError:
                unchanged = False
            if unchanged:
                _CONTENT_DIGESTS[key] = content_digest
    return data


def _uses_reference_implementations() -> bool:
    """True unless a caller replaced an analysis stage (e.g. a test double)."""
    from . import pipeline, stego

    return (
        extract_all_idr_blocks is pipeline.extract_all_idr_blocks
        and CAVLCSafetyFilter is stego.CAVLCSafetyFilter
        and _build_reconstruction_context is _REFERENCE_BUILD_RECONSTRUCTION_CONTEXT
        and H264BitstreamParser is _REFERENCE_PARSER
        and BitstreamReconstructor is _REFERENCE_RECONSTRUCTOR
    )


def _try_parallel_analysis(
    path: Path,
    parser: H264BitstreamParser,
    *,
    stable_blind_only: bool,
    signbit_only: bool,
) -> tuple[tuple, dict[str, Any]] | None:
    """Build the analysis in worker processes when that is exactly equivalent.

    Returns ``None`` to request the serial reference path, which also owns
    every error report.
    """
    from .parallel_analysis import build_parallel_analysis, configured_worker_count

    workers = configured_worker_count()
    if workers < 2 or not _uses_reference_implementations():
        return None
    context = _build_reconstruction_context(path, parser=parser)
    data = build_parallel_analysis(
        path,
        parser,
        context,
        stable_blind_only=stable_blind_only,
        signbit_only=signbit_only,
        workers=workers,
    )
    if data is None:
        return None
    return data, context


def _build_serial_analysis(
    path: Path,
    parser: H264BitstreamParser,
    *,
    stable_blind_only: bool,
    signbit_only: bool,
) -> tuple[tuple, dict[str, Any]]:
    """Reference analysis: parse all IDR frames, then run the safety filter."""
    reconstructor = BitstreamReconstructor()
    coefficients, frame_verified_data, n_c_map, nal_length_map, t1_override_map = extract_all_idr_blocks(
        str(path), reconstructor, parser=parser
    )
    if stable_blind_only and (not frame_verified_data or not nal_length_map):
        raise RuntimeError(
            "stable blind analysis requires trusted CAVLC offsets and patchability metadata"
        )
    context = _build_reconstruction_context(path, parser=parser)
    sps = context.get("sps")
    if sps is not None and not getattr(sps, "frame_mbs_only_flag", True):
        # Map units would be macroblock pairs, so the per-picture macroblock count
        # (and every IDR offset derived from it) would be wrong. Fail closed.
        raise RuntimeError("interlaced H.264 (frame_mbs_only_flag=0) is not supported")
    safe_positions = CAVLCSafetyFilter().get_safe_positions(
        coefficients,
        nC_map=n_c_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
        frame_verified_data=frame_verified_data,
        # Macroblocks per picture from the SPS; the CIF default would map every
        # macroblock past the first 396 of a larger frame to a missing IDR.
        cif_mb_count=int(context.get("mb_count_per_slice") or 396),
        stable_carriers_only=stable_blind_only,
        signbit_only=signbit_only,
    )
    data = (coefficients, frame_verified_data, n_c_map, nal_length_map, t1_override_map, safe_positions)
    return data, context


def load_or_build_reconstruction_context(
    video_path: str | Path,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return trusted, process-local reconstruction context."""
    _warn_legacy_cache_dir(cache_dir)
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    key = _cache_key(path)
    fingerprint = _video_fingerprint(path)
    with _LOCK:
        cached = _RECONSTRUCTION_CONTEXT_CACHE.get(key)
        if use_cache and not force_refresh and cached and cached[0] == fingerprint:
            return cached[1]
        _evict_other_cached_videos(None)

    data = _build_reconstruction_context(path)
    if use_cache:
        with _LOCK:
            _evict_other_cached_videos(key)
            _RECONSTRUCTION_CONTEXT_CACHE[key] = (fingerprint, data)
    return data


def clear_video_analysis_cache(cache_dir: str | Path | None = None) -> int:
    """Clear the process-local cache and return the number of entries removed."""
    _warn_legacy_cache_dir(cache_dir)
    with _LOCK:
        count = len(_VIDEO_ANALYSIS_CACHE) + len(_RECONSTRUCTION_CONTEXT_CACHE)
        _VIDEO_ANALYSIS_CACHE.clear()
        _RECONSTRUCTION_CONTEXT_CACHE.clear()
        _CONTENT_DIGESTS.clear()
        _PARKED["key"] = None
    return count
