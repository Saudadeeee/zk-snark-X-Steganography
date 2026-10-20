"""Process-parallel original-video analysis that reproduces the serial result.

``load_or_build_video_analysis`` parses every IDR NAL with the traceable
CAVLC parser and then runs the safety filter over all luma blocks. Both steps
are pure functions of one IDR NAL (plus the stream's SPS/PPS) whenever every
block of that NAL lies inside its own picture's macroblock range: the parser
resets its neighbour state per NAL and the safety filter only consults the
block's own frame entry. This module computes those per-frame pieces in
worker processes and merges them in stream order, building every dictionary
in the same insertion order as the serial code.

The parallel path is an accelerator only. Whenever a precondition does not
hold (fewer frames than worth spawning for, a frame whose blocks fall outside
its picture, an untrusted parse, a worker failure, ...) it returns ``None``
and the caller runs the serial implementation, which remains the reference
and produces any error exactly as before.

Workers are fresh interpreters started with ``-I -c`` (no ``__main__``
re-import) and exchange ``marshal`` data over pipes with their own parent; no
cache is persisted and nothing is read back from disk.
"""

from __future__ import annotations

import logging
import marshal
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WORKERS_ENV = "ZKSTEGO_ANALYSIS_WORKERS"
DEFAULT_MAX_WORKERS = 8
MIN_FRAMES_PER_WORKER = 2
_MARSHAL_VERSION = 4
_JOB_VERSION = 1


def configured_worker_count() -> int:
    """Return the worker budget: ``ZKSTEGO_ANALYSIS_WORKERS`` or a CPU default.

    ``0`` or ``1`` disables process parallelism (serial reference path).
    """
    raw = os.environ.get(WORKERS_ENV, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("ignoring non-integer %s=%r", WORKERS_ENV, raw)
    return max(1, min(DEFAULT_MAX_WORKERS, os.cpu_count() or 1))


def _nal_fields(nal) -> tuple:
    return (
        int(nal.forbidden_zero_bit),
        int(nal.nal_ref_idc),
        int(nal.nal_unit_type),
        bytes(nal.rbsp_byte),
        int(nal.start_pos),
        int(nal.size),
        int(nal.start_code_size),
    )


def _nal_from_fields(fields: tuple):
    from ..bitstream.h264 import NALUnit, NALUnitType

    forbidden, ref_idc, unit_type, rbsp, start_pos, size, start_code_size = fields
    try:
        nal_type = NALUnitType(unit_type)
    except ValueError:
        nal_type = NALUnitType.UNKNOWN
    return NALUnit(
        forbidden_zero_bit=forbidden,
        nal_ref_idc=ref_idc,
        nal_unit_type=nal_type,
        rbsp_byte=rbsp,
        start_pos=start_pos,
        size=size,
        start_code_size=start_code_size,
    )


def _frame_is_self_contained(idr_off: int, cif_mb_count: int, g_off: dict, g_blk: dict) -> bool:
    """True when every block of the frame maps back to this frame's IDR offset."""
    for mb, _block in g_off:
        if (mb // cif_mb_count) * cif_mb_count != idr_off:
            return False
    for mb, _block in g_blk:
        if (mb // cif_mb_count) * cif_mb_count != idr_off:
            return False
    return True


def analyse_frames(job: dict) -> list:
    """Worker body: parse and safety-filter a contiguous run of IDR frames.

    Each entry is ``None`` (caller must use the serial path) or
    ``(idr_coeffs, g_off, g_blk, nC_map, nal_length_map, t1_override_map,
    safe_positions)`` where ``safe_positions`` is the frame's un-interleaved
    safety-filter output.
    """
    from ..bitstream.bitstream_ops import BitstreamReconstructor
    from ..bitstream.h264 import TraceableCAVLCParser
    from .pipeline import _extract_idr_frame
    from .stego import CAVLCSafetyFilter

    if job.get("version") != _JOB_VERSION:
        raise ValueError("unsupported analysis job version")
    reconstructor = BitstreamReconstructor()
    sps = reconstructor._parse_sps_from_nal(_nal_from_fields(job["sps_nal"]))
    pps = reconstructor._parse_pps_from_nal(_nal_from_fields(job["pps_nal"]))
    cif_mb_count = int(job["cif_mb_count"])
    traceable = TraceableCAVLCParser()
    results: list = []
    for nal_index, idr_off, fields in job["frames"]:
        nal = _nal_from_fields(fields)
        try:
            frame = _extract_idr_frame(traceable, nal, nal_index, sps, pps, idr_off)
        except RuntimeError:
            results.append(None)
            continue
        idr_coeffs, g_off, g_blk, n_c_map, nal_length_map, t1_override_map = frame
        if not _frame_is_self_contained(idr_off, cif_mb_count, g_off, g_blk):
            results.append(None)
            continue
        if idr_coeffs and not nal_length_map:
            # The serial filter's behaviour depends on whether the *global*
            # length map is empty; this frame alone cannot decide that.
            results.append(None)
            continue
        safe_positions: list = []
        if idr_coeffs:
            safe_positions = CAVLCSafetyFilter().get_safe_positions(
                idr_coeffs,
                nC_map=n_c_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map,
                frame_verified_data={idr_off: (g_off, g_blk, nal.rbsp_byte)},
                cif_mb_count=cif_mb_count,
                stable_carriers_only=bool(job["stable_blind_only"]),
                signbit_only=bool(job["signbit_only"]),
                interleave_positions=False,
            )
        results.append(
            (idr_coeffs, g_off, g_blk, n_c_map, nal_length_map, t1_override_map, safe_positions)
        )
    return results


def _worker_main() -> None:
    """Entry point of a worker interpreter: marshal job in, marshal result out."""
    output = sys.stdout.buffer
    # Anything a library prints must not corrupt the marshal stream.
    sys.stdout = sys.stderr
    job = marshal.loads(sys.stdin.buffer.read())
    payload = marshal.dumps(analyse_frames(job), _MARSHAL_VERSION)
    output.write(payload)
    output.flush()


def _worker_command() -> list[str]:
    package_depth = len(__name__.split(".")) - 1
    import_root = str(Path(__file__).resolve().parents[package_depth])
    bootstrap = (
        "import sys, importlib; "
        f"sys.path.insert(0, {import_root!r}); "
        f"importlib.import_module({__name__!r})._worker_main()"
    )
    command = [sys.executable, "-I"]
    if sys.dont_write_bytecode:
        command.append("-B")
    return [*command, "-c", bootstrap]


def _run_jobs(jobs: list[dict]) -> list[list] | None:
    """Run each job in its own worker process; ``None`` if any worker fails."""
    command = _worker_command()
    processes: list[subprocess.Popen] = []
    try:
        for _job in jobs:
            processes.append(
                subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        payloads = [marshal.dumps(job, _MARSHAL_VERSION) for job in jobs]
        with ThreadPoolExecutor(max_workers=len(processes)) as pool:
            outputs = list(
                pool.map(
                    lambda pair: pair[0].communicate(pair[1]),
                    zip(processes, payloads),
                )
            )
    except OSError as error:
        logger.warning("parallel analysis unavailable (%s); using serial analysis", error)
        return None
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    results = []
    for process, (stdout, stderr) in zip(processes, outputs):
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip()[-2000:]
            logger.warning(
                "parallel analysis worker failed (%s); using serial analysis: %s",
                process.returncode,
                detail,
            )
            return None
        if stderr.strip():
            logger.debug(
                "parallel analysis worker diagnostics: %s",
                stderr.decode("utf-8", "replace").strip()[-2000:],
            )
        try:
            results.append(marshal.loads(stdout))
        except (EOFError, ValueError, TypeError) as error:
            logger.warning("parallel analysis returned unreadable data (%s)", error)
            return None
    return results


def build_parallel_analysis(
    path: Path,
    parser: Any,
    context: dict[str, Any],
    *,
    stable_blind_only: bool,
    signbit_only: bool,
    workers: int,
) -> tuple | None:
    """Return the analysis tuple the serial path would build, or ``None``.

    ``context`` must be ``_build_reconstruction_context(path, parser=parser)``.
    Only the happy path is handled here; ``None`` defers every other case
    (including every error the serial path raises) to the serial code.
    """
    from ..bitstream.bitstream_ops import BitstreamReconstructor
    from .pipeline import _idr_frame_jobs, _parse_parameter_sets
    from .stego import _CIF_MB_COUNT, sort_blocks_interleaved

    if workers < 2:
        return None
    try:
        _sps, _pps, mb_count, sps_nal, pps_nal = _parse_parameter_sets(
            parser, BitstreamReconstructor()
        )
    except Exception:  # noqa: BLE001 - the serial path reproduces the error
        return None
    sps = context.get("sps")
    if sps is not None and not getattr(sps, "frame_mbs_only_flag", True):
        return None
    frames = _idr_frame_jobs(parser.nal_units, mb_count)
    worker_count = min(workers, len(frames) // MIN_FRAMES_PER_WORKER)
    if worker_count < 2:
        return None

    cif_mb_count = int(context.get("mb_count_per_slice") or 396)
    per_worker = math.ceil(len(frames) / worker_count)
    jobs = []
    for start in range(0, len(frames), per_worker):
        jobs.append(
            {
                "version": _JOB_VERSION,
                "sps_nal": _nal_fields(sps_nal),
                "pps_nal": _nal_fields(pps_nal),
                "cif_mb_count": cif_mb_count,
                "stable_blind_only": bool(stable_blind_only),
                "signbit_only": bool(signbit_only),
                "frames": [
                    (nal_index, idr_off, _nal_fields(nal))
                    for nal_index, nal, idr_off in frames[start:start + per_worker]
                ],
            }
        )
    job_results = _run_jobs(jobs)
    if job_results is None:
        return None
    frame_results = [frame for job_result in job_results for frame in job_result]
    if len(frame_results) != len(frames):
        return None

    coefficients: list = []
    frame_verified_data: dict = {}
    n_c_map: dict = {}
    nal_length_map: dict = {}
    t1_override_map: dict = {}
    magnitude_positions: list = []
    sign_positions: list = []
    for (_nal_index, nal, idr_off), frame in zip(frames, frame_results):
        if frame is None:
            return None
        idr_coeffs, g_off, g_blk, frame_nc, frame_lengths, frame_t1, frame_safe = frame
        coefficients.extend(idr_coeffs)
        # The serial analysis keeps the parser's own RBSP object.
        frame_verified_data[idr_off] = (g_off, g_blk, nal.rbsp_byte)
        n_c_map.update(frame_nc)
        nal_length_map.update(frame_lengths)
        t1_override_map.update(frame_t1)
        for position in frame_safe:
            if position[2] < 0:
                sign_positions.append(position)
            else:
                magnitude_positions.append(position)
    if not coefficients:
        return None
    if stable_blind_only and (not frame_verified_data or not nal_length_map):
        return None

    # The serial filter appends every magnitude carrier (all frames) before
    # every sign carrier; only the stable profile returns that list as is.
    safe_positions = magnitude_positions + sign_positions
    if not stable_blind_only:
        safe_positions = sort_blocks_interleaved(safe_positions, _CIF_MB_COUNT)
    return (
        coefficients,
        frame_verified_data,
        n_c_map,
        nal_length_map,
        t1_override_map,
        safe_positions,
    )
