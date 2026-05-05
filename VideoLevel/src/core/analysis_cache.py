"""
analysis_cache.py - Runtime cache for expensive original-video analysis.

Caches the immutable analysis derived from an original cover video:
  - extracted IDR coefficients
  - frame_verified_data
  - nC / NAL length / T1 override maps
  - safe_positions from CAVLCSafetyFilter

This is intended for application/runtime usage, unlike benchmark-only caches.
"""

from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path
from typing import Any

from ..bitstream.bitstream_ops import BitstreamReconstructor
from ..bitstream.h264 import H264BitstreamParser
from .pipeline import extract_all_idr_blocks
from .stego import CAVLCSafetyFilter


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_DIR = ROOT / ".cache" / "video_analysis"
CACHE_SCHEMA_VERSION = 1


def _cache_path(video_path: str | Path, cache_dir: str | Path | None = None) -> Path:
    base = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    vp = Path(video_path)
    try:
        resolved = str(vp.resolve()).encode("utf-8")
    except OSError:
        resolved = str(vp).encode("utf-8")
    path_hash = hashlib.sha1(resolved).hexdigest()[:12]
    return base / f"{vp.stem}_{path_hash}.pkl"


def _code_fingerprint() -> dict[str, int | str]:
    files = [
        ROOT / "src" / "core" / "analysis_cache.py",
        ROOT / "src" / "core" / "pipeline.py",
        ROOT / "src" / "core" / "stego.py",
        ROOT / "src" / "bitstream" / "h264.py",
        ROOT / "src" / "bitstream" / "bitstream_ops.py",
    ]
    fp: dict[str, int | str] = {"schema": CACHE_SCHEMA_VERSION}
    for f in files:
        key = f.relative_to(ROOT).as_posix()
        try:
            fp[key] = int(f.stat().st_mtime_ns)
        except OSError:
            fp[key] = "missing"
    return fp


def _video_fingerprint(video_path: str | Path) -> dict[str, Any]:
    vp = Path(video_path)
    stat = vp.stat()
    return {
        "path": str(vp.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "code": _code_fingerprint(),
    }


def _build_reconstruction_context(video_path: str | Path,
                                  parser: H264BitstreamParser | None = None) -> dict[str, Any]:
    vp = Path(video_path)
    if parser is None:
        parser = H264BitstreamParser(str(vp))
        parser.parse()

    rec = BitstreamReconstructor()
    sps = None
    pps = None
    for nal in parser.nal_units:
        if int(nal.nal_unit_type) == 7:
            try:
                sps = rec._parse_sps_from_nal(nal)
            except Exception:
                pass
        elif int(nal.nal_unit_type) == 8:
            try:
                pps = rec._parse_pps_from_nal(nal)
            except Exception:
                pass

    if sps is not None:
        mb_count_per_slice = (
            (sps.pic_width_in_mbs_minus1 + 1) *
            (sps.pic_height_in_map_units_minus1 + 1)
        )
    else:
        mb_count_per_slice = 264

    return {
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
) -> tuple:
    """
    Return:
      (coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map, safe_positions)
    """
    vp = Path(video_path)
    if not vp.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cache_path = _cache_path(vp, cache_dir)
    fingerprint = _video_fingerprint(vp)

    if use_cache and not force_refresh and cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)
            if payload.get("fingerprint") == fingerprint and "data" in payload:
                return payload["data"]
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
            pass

    parser = H264BitstreamParser(str(vp))
    parser.parse()

    rec = BitstreamReconstructor()
    coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map = (
        extract_all_idr_blocks(str(vp), rec, parser=parser)
    )

    safety = CAVLCSafetyFilter()
    safe_positions = safety.get_safe_positions(
        coefficients,
        nC_map=nC_map,
        nal_length_map=nal_length_map,
        t1_override_map=t1_override_map,
    )

    data = (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        safe_positions,
    )

    if use_cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                pickle.dump({"fingerprint": fingerprint, "data": data}, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass

        # Also persist reconstruction context from the same parsed bitstream so
        # cold-start embed paths do not need to parse the video a second time.
        try:
            recon_path = cache_path.with_name(cache_path.stem + "_recon.pkl")
            recon_data = _build_reconstruction_context(vp, parser=parser)
            with open(recon_path, "wb") as f:
                pickle.dump({"fingerprint": fingerprint, "data": recon_data}, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass

    return data


def load_or_build_reconstruction_context(
    video_path: str | Path,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return cached reconstruction context for repeated patch/write operations:
      {
        "nal_units": list[NALUnit],
        "sps": SPSData | None,
        "pps": PPSData | None,
        "mb_count_per_slice": int,
      }
    """
    vp = Path(video_path)
    if not vp.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cache_path = _cache_path(vp, cache_dir).with_name(_cache_path(vp, cache_dir).stem + "_recon.pkl")
    fingerprint = _video_fingerprint(vp)

    if use_cache and not force_refresh and cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)
            if payload.get("fingerprint") == fingerprint and "data" in payload:
                return payload["data"]
        except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
            pass

    data = _build_reconstruction_context(vp)

    if use_cache:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "wb") as f:
                pickle.dump({"fingerprint": fingerprint, "data": data}, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            pass

    return data


def clear_video_analysis_cache(cache_dir: str | Path | None = None) -> int:
    base = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    if not base.exists():
        return 0
    removed = 0
    for p in base.glob("*.pkl"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed
