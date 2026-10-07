"""Streaming reader for ``zkstego_inspect <file.h264>`` traces.

The inspector prints one JSON object whose last key is ``"candidates"``; for
1080p streams that list can reach hundreds of MB. The header (``nals`` and
``slices``) is parsed once and every candidate object is decoded on the fly
into compact numpy columns, so memory stays proportional to the candidate
count rather than the JSON text.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import numpy as np

from .common import INSPECT_EXE

_CANDIDATES_KEY = '"candidates":['
_CHUNK = 1 << 20


@dataclass(frozen=True)
class CavlcTrace:
    """Column store of every trailing-one candidate of a stream.

    ``coeffs`` holds ``coefficients_scan`` padded to 16 entries (zig-zag
    order; 15-entry AC blocks and 4-entry chroma DC blocks are zero padded).
    ``frame`` maps each candidate to its picture index in decoding order.
    """

    nal: np.ndarray
    mb: np.ndarray
    cat: np.ndarray
    blk: np.ndarray
    bit: np.ndarray
    mb_type: np.ndarray
    total_coeff: np.ndarray
    trailing_ones: np.ndarray
    coeff_len: np.ndarray
    coeffs: np.ndarray
    frame: np.ndarray
    frame_mb_width: dict[int, int]
    frame_mb_height: dict[int, int]
    frame_qp: dict[int, int]

    @property
    def count(self) -> int:
        return int(self.nal.shape[0])


def _iter_batches(stream: IO[str]) -> Iterator[dict | list[dict]]:
    """Yield the header dict once, then lists of candidate dicts.

    Candidate objects are flat, so ``},{`` only occurs between two candidates;
    each read chunk is cut at its last such separator and decoded with a
    single ``json.loads`` call.
    """
    buffer = ""
    while _CANDIDATES_KEY not in buffer:
        chunk = stream.read(_CHUNK)
        if not chunk:
            raise ValueError("inspector output has no candidates list")
        buffer += chunk
    split = buffer.index(_CANDIDATES_KEY)
    yield json.loads(buffer[:split].rstrip().rstrip(",") + "}")
    buffer = buffer[split + len(_CANDIDATES_KEY):]
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            tail = buffer.rstrip()
            if not tail.endswith("]}"):
                raise ValueError("truncated inspector output")
            yield json.loads("[" + tail[:-1])
            return
        buffer += chunk
        cut = buffer.rfind("},{")
        if cut >= 0:
            yield json.loads("[" + buffer[:cut + 1] + "]")
            buffer = buffer[cut + 2:]


def _frame_of_nal(header: dict) -> tuple[dict[int, int], dict[int, dict]]:
    """Picture index for every VCL NAL (a new picture starts at first_mb == 0)."""
    slices = {int(s["nal_index"]): s for s in header.get("slices", [])}
    frame_of: dict[int, int] = {}
    frame = -1
    for nal in header.get("nals", []):
        if int(nal["type"]) not in (1, 5):
            continue
        index = int(nal["index"])
        info = slices.get(index)
        if info is None or int(info.get("first_mb", 0)) == 0 or frame < 0:
            frame += 1
        frame_of[index] = frame
    return frame_of, slices


def parse_trace(stream: IO[str]) -> CavlcTrace:
    batches = _iter_batches(stream)
    header = next(batches)
    assert isinstance(header, dict)
    frame_of, slices = _frame_of_nal(header)
    ids: list[list[int]] = []
    scalars: list[tuple[int, int, int, int, int]] = []
    rows: list[list[int]] = []
    for candidate in (item for batch in batches for item in batch):
        ids.append(candidate["id"])
        coefficients = candidate["coefficients_scan"]
        scalars.append((candidate["bit"], candidate["mb_type"], candidate["total_coeff"],
                        candidate["trailing_ones"], len(coefficients)))
        rows.append(coefficients + [0] * (16 - len(coefficients)))
    count = len(ids)
    id_array = np.asarray(ids, dtype=np.int64).reshape(count, 5)
    scalar_array = np.asarray(scalars, dtype=np.int32).reshape(count, 5)
    coeffs = np.asarray(rows, dtype=np.int16).reshape(count, 16)
    nal = id_array[:, 0].astype(np.int32)
    frame = np.asarray([frame_of.get(int(n), -1) for n in nal], dtype=np.int32)
    widths, heights, qps = {}, {}, {}
    for index, info in slices.items():
        picture = frame_of.get(index, -1)
        widths[picture] = int(info["mb_width"])
        heights[picture] = int(info["mb_height"])
        qps.setdefault(picture, int(info.get("initial_qp", 0)))
    return CavlcTrace(nal, id_array[:, 1].astype(np.int32), id_array[:, 2].astype(np.int8),
                      id_array[:, 3].astype(np.int8), scalar_array[:, 0].astype(np.int8),
                      scalar_array[:, 1].astype(np.int16), scalar_array[:, 2].astype(np.int8),
                      scalar_array[:, 3].astype(np.int8), scalar_array[:, 4].astype(np.int8), coeffs, frame,
                      widths, heights, qps)


def load_trace(path: Path, inspect_exe: Path = INSPECT_EXE) -> CavlcTrace:
    """Run the inspector on ``path`` and parse its trace incrementally."""
    command = [str(inspect_exe), str(path)]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8") as process:
        assert process.stdout is not None
        try:
            trace = parse_trace(process.stdout)
        finally:
            process.stdout.read()
            stderr = process.stderr.read() if process.stderr else ""
            process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"zkstego_inspect failed on {path}: {stderr.strip()[:300]}")
    return trace
