"""Method-agnostic trailing-one sign embedding on H.264 Annex-B streams (evaluation framework).

Every compared method uses the same channel: it chooses N candidate signs per IDR
picture and writes one independent random bit into each (about half of them change,
as with the whitened frame bits of the real codec). Methods differ only in which
candidates they choose, so quality and detectability differences come from the
selection rule. The real codec (native, keyed HMAC schedule) is a uniform keyed
choice and is represented here by the ``random`` rule; end-to-end runs of the native
tools are reported separately.

Candidates come from ``zkstego_inspect`` run on one IDR access unit at a time (the
latest SPS/PPS plus the IDR), which keeps 1080p traces small. Bits are flipped in
the RBSP and the NAL unit is re-escaped with emulation-prevention bytes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from benchmark.media_benchmark_new import _inspect_binary
from src.video_binding import ebsp_to_rbsp, split_annex_b

NAL_IDR, NAL_SPS, NAL_PPS = 5, 7, 8


@dataclass(frozen=True)
class Candidate:
    """One first-trailing-one sign of an IDR block, located in the whole file."""
    frame: int            # IDR order in the file (0-based)
    nal: int              # file NAL index
    rbsp_bit: int
    mb: int
    mb_row: int
    mb_col: int
    mb_height: int
    category: int         # 0 LumaDC, 1 Luma4x4/AC, 2 ChromaDC, 3 ChromaAC
    block: int
    mb_type: int          # 0 = Intra4x4
    total_coeff: int
    trailing_ones: int
    scan: tuple[int, ...]
    bit: int              # cover sign bit (0 '+', 1 '-')
    signs: tuple[tuple[int, int], ...] = ()  # (RBSP bit, sign) of every trailing one, highest frequency first

    def identity(self) -> bytes:
        return f"{self.nal}:{self.mb}:{self.category}:{self.block}:{self.rbsp_bit}".encode("ascii")


def rbsp_to_ebsp(rbsp: bytes) -> bytes:
    """Insert emulation-prevention bytes (03 after 00 00 when the next byte is <= 03)."""
    out = bytearray()
    zeros = 0
    for byte in rbsp:
        if zeros >= 2 and byte <= 0x03:
            out.append(0x03)
            zeros = 0
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def _units_with_start_codes(data: bytes) -> list[tuple[bytes, int, bytes]]:
    """(start code, header byte, EBSP) per NAL unit, preserving 3/4-byte start codes."""
    units, cursor = [], 0
    starts = []
    while cursor < len(data) - 2:
        if data[cursor:cursor + 3] == b"\x00\x00\x01":
            long = cursor > 0 and data[cursor - 1] == 0
            starts.append((cursor - 1 if long else cursor, cursor + 3))
            cursor += 3
        else:
            cursor += 1
    for index, (code_start, header) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(data)
        units.append((data[code_start:header], data[header], data[header + 1:end]))
    if len(units) != len(split_annex_b(data)):
        raise RuntimeError("start-code split disagrees with the reference splitter")
    return units


def _trace(path: Path) -> dict:
    result = subprocess.run([str(_inspect_binary()), str(path)], capture_output=True, check=False, timeout=600)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-300:])
    return json.loads(result.stdout)


def _signs(candidate: dict) -> tuple[tuple[int, int], ...]:
    """Trailing-one sign flags of a block: the last non-zero coefficients in scan order, highest first."""
    nonzero = [value for value in reversed(candidate["coefficients_scan"]) if value]
    offsets = candidate["sign_offsets"]
    if len(offsets) != candidate["trailing_ones"] or any(abs(v) != 1 for v in nonzero[:len(offsets)]):
        raise RuntimeError("unexpected trailing-one layout in trace")
    signs = tuple((offset, int(value < 0)) for offset, value in zip(offsets, nonzero))
    if signs[0] != (candidate["id"][4], candidate["bit"]):
        raise RuntimeError("first sign flag does not match the candidate")
    return signs


def candidates(path: Path, workers: int = 6) -> list[Candidate]:
    """Candidates of every IDR of an Annex-B file (inspected one access unit at a time)."""
    units = _units_with_start_codes(path.read_bytes())
    jobs, sps, pps = [], None, None
    for index, (_, header, ebsp) in enumerate(units):
        kind = header & 0x1F
        if kind == NAL_SPS:
            sps = (header, ebsp)
        elif kind == NAL_PPS:
            pps = (header, ebsp)
        elif kind == NAL_IDR:
            if sps is None or pps is None:
                raise RuntimeError("IDR without SPS/PPS")
            jobs.append((len(jobs), index, sps, pps, (header, ebsp)))

    def run(job: tuple) -> list[Candidate]:
        frame, file_nal, *parts = job
        with tempfile.TemporaryDirectory() as folder:
            au = Path(folder) / "au.h264"
            au.write_bytes(b"".join(b"\x00\x00\x00\x01" + bytes((h,)) + e for h, e in parts))
            trace = _trace(au)
        info = trace["slices"][0]
        width, height = info["mb_width"], info["mb_height"]
        return [Candidate(frame, file_nal, c["id"][4], c["id"][1], c["id"][1] // width, c["id"][1] % width, height,
                          c["id"][2], c["id"][3], c["mb_type"], c["total_coeff"], c["trailing_ones"],
                          tuple(c["coefficients_scan"]), c["bit"], _signs(c))
                for c in trace["candidates"] if c["id"][0] == 2]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        per_frame = list(pool.map(run, jobs))
    return [c for frame in per_frame for c in frame]


def keyed_order(items: list[Candidate], key: bytes) -> list[Candidate]:
    """Uniform keyed permutation: sort by (HMAC(key, identity), identity)."""
    return sorted(items, key=lambda c: (hmac.new(key, c.identity(), hashlib.sha256).digest(), c.identity()))


BitSource = Callable[[int], int]
# A method places message bits into one IDR: (candidates, bits wanted, per-frame key, bit source)
# -> (RBSP bits to flip as (nal, bit) pairs, number of message bits embedded).
Method = Callable[[list[Candidate], int, bytes, BitSource], tuple[list[tuple[int, int]], int]]


def write_first_signs(chosen: list[Candidate], bit: BitSource) -> list[tuple[int, int]]:
    """Plain sign embedding: message bit i becomes the first trailing-one sign of chosen[i]."""
    return [(c.nal, c.rbsp_bit) for i, c in enumerate(chosen) if bit(i) != c.bit]


def embed(cover: Path, output: Path, cands: list[Candidate], method: Method, bits_per_idr: Callable[[int], int],
          key: bytes) -> dict:
    """Embed random message bits with `method` into every IDR; returns embedding statistics."""
    by_frame: dict[int, list[Candidate]] = {}
    for cand in cands:
        by_frame.setdefault(cand.frame, []).append(cand)
    flips: dict[int, list[int]] = {}
    embedded_total = changed_total = 0
    per_frame = {}
    for frame, items in sorted(by_frame.items()):
        frame_key = key + frame.to_bytes(4, "big")
        wanted = min(bits_per_idr(len(items)), len(items))
        stream = hashlib.shake_256(b"message-bits" + frame_key).digest((wanted + 7) // 8 + 1)
        bit = lambda i, data=stream: (data[i // 8] >> (7 - i % 8)) & 1  # noqa: E731
        changes, embedded = method(items, wanted, frame_key, bit)
        if len(set(changes)) != len(changes):
            raise RuntimeError("a method flipped the same sign twice")
        for nal, offset in changes:
            flips.setdefault(nal, []).append(offset)
        per_frame[frame] = {"candidates": len(items), "wanted": wanted, "embedded": embedded, "changed": len(changes)}
        embedded_total += embedded
        changed_total += len(changes)
    units = _units_with_start_codes(cover.read_bytes())
    pieces = []
    for index, (code, header, ebsp) in enumerate(units):
        if index in flips:
            rbsp = bytearray(ebsp_to_rbsp(ebsp))
            for offset in flips[index]:
                rbsp[offset // 8] ^= 0x80 >> (offset % 8)
            if rbsp_to_ebsp(bytes(ebsp_to_rbsp(ebsp))) != ebsp:
                raise RuntimeError(f"NAL {index}: re-escaping does not reproduce the cover EBSP")
            ebsp = rbsp_to_ebsp(bytes(rbsp))
        pieces.append(code + bytes((header,)) + ebsp)
    output.write_bytes(b"".join(pieces))
    return {"embedded": embedded_total, "changed": changed_total, "frames": per_frame,
            "cover_bytes": cover.stat().st_size, "stego_bytes": output.stat().st_size}
