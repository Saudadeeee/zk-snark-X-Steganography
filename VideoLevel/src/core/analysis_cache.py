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


def _cache_key(video_path: str | Path) -> str:
    return str(Path(video_path).resolve())


def _code_fingerprint() -> dict[str, int | str]:
    files = [
        ROOT / "src" / "core" / "analysis_cache.py",
        ROOT / "src" / "core" / "pipeline.py",
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
    for cache in (_VIDEO_ANALYSIS_CACHE, _RECONSTRUCTION_CONTEXT_CACHE):
        for cached_key in tuple(cache):
            if active_key is None or cached_key != active_key:
                cache.pop(cached_key, None)


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


def load_or_build_video_analysis(
    video_path: str | Path,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = None,
    stable_blind_only: bool = False,
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
        "analysis_profile": "stable-blind-v1" if stable_blind_only else "full-v1",
    }
    with _LOCK:
        cached = _VIDEO_ANALYSIS_CACHE.get(key)
        if use_cache and not force_refresh and cached and cached[0] == fingerprint:
            return cached[1]
        _evict_other_cached_videos(None)

    parser = H264BitstreamParser(str(path))
    parser.parse()
    reconstructor = BitstreamReconstructor()
    coefficients, frame_verified_data, n_c_map, nal_length_map, t1_override_map = extract_all_idr_blocks(
        str(path), reconstructor, parser=parser
    )
    if stable_blind_only and (not frame_verified_data or not nal_length_map):
        raise RuntimeError(
            "stable blind analysis requires trusted CAVLC offsets and patchability metadata"
        )
    safe_positions = CAVLCSafetyFilter().get_safe_positions(
        coefficients,
        nC_map=n_c_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
        frame_verified_data=frame_verified_data,
        stable_carriers_only=stable_blind_only,
    )
    data = (coefficients, frame_verified_data, n_c_map, nal_length_map, t1_override_map, safe_positions)

    if use_cache:
        context = _build_reconstruction_context(path, parser=parser)
        with _LOCK:
            _evict_other_cached_videos(key)
            _VIDEO_ANALYSIS_CACHE[key] = (fingerprint, data)
            _RECONSTRUCTION_CONTEXT_CACHE[key] = (video_fingerprint, context)
    return data


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
    return count
