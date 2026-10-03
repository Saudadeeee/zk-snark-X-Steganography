"""Segment-protocol schedule helpers for terminal_demo.py.

The native codec treats every IDR as one segment (SPS/PPS + that IDR) carrying at
most ``max_bits_per_idr`` frame bits; ``segment_schedule`` reproduces its exact
placements from ``zkstego_inspect --segments``. These helpers pick the cap, map
segment identities back to whole-file candidates and print the allocation.
"""
from __future__ import annotations

from dataclasses import dataclass

import deep_trace
from src.native_blind_contract import NativeCavlcCandidate, SchedulePlacement

DEFAULT_MAX_BITS_PER_IDR = 64  # same default as the native HTTP/WebSocket service


@dataclass(frozen=True)
class EmbedPlan:
    """The segment-protocol schedule of one payload, reproduced from zkstego_inspect --segments."""
    max_bits: int
    segments: dict
    placements: list[SchedulePlacement]
    selected: list[NativeCavlcCandidate]  # whole-file identities, in frame-bit order
    bits: list[int]                       # embedded (whitened) bits, in frame-bit order
    frame: bytes                          # plaintext authenticated frame v2


def file_candidate(placement: SchedulePlacement) -> NativeCavlcCandidate:
    """Whole-file identity of a segment candidate (the segment id uses the analysis NAL index)."""
    identity = placement.candidate.identity
    return NativeCavlcCandidate(placement.candidate.nal_index, identity.macroblock_address, identity.category,
                                identity.block_index, placement.candidate.rbsp_bit_offset)


def segment_capacity(segments: dict, max_bits: int) -> int:
    return sum(min(max_bits, row["candidate_count"]) for row in segments["segments"])


def resolve_max_bits(session, segments: dict, required_bits: int) -> int:
    """--max-bits-per-idr if given; otherwise 64, raised to the smallest cap that fits a short clip."""
    requested = session.args.max_bits_per_idr
    cap = requested or DEFAULT_MAX_BITS_PER_IDR
    largest = max((row["candidate_count"] for row in segments["segments"]), default=0)
    if segment_capacity(segments, cap) >= required_bits:
        return cap
    if requested is None and segment_capacity(segments, max(largest, cap)) >= required_bits:
        low, high = cap, max(largest, cap)
        while low < high:  # capacity(cap) is monotone: smallest sufficient cap
            middle = (low + high) // 2
            low, high = (middle + 1, high) if segment_capacity(segments, middle) < required_bits else (low, middle)
        session.say(f"Mac dinh {DEFAULT_MAX_BITS_PER_IDR} bit/IDR chi cho {segment_capacity(segments, cap)} bit < can"
                    f" {required_bits}; clip ngan nen demo tu nang len {low} bit/IDR (gia tri nho nhat du capacity).")
        session.say("Ca embed, extract, HTTP va WebSocket ben duoi deu dung cung gia tri nay.")
        return low
    raise RuntimeError(
        f"Khong du capacity: {len(segments['segments'])} IDR segment, cap {cap} bit/IDR -> "
        f"{segment_capacity(segments, cap)} bit, toi da {segment_capacity(segments, max(largest, 1))} bit, can {required_bits}. "
        "Tang --frames, giam --gop, tang --max-bits-per-idr hoac rut ngan message.")


def show_allocation(session, segments: dict, placements: list[SchedulePlacement],
                    max_bits: int, message_bytes: int) -> None:
    session.say("Phan bo theo segment: IDR nao mang khoang frame bit nao")
    session.say(" seg  IDR NAL  analysis NAL  candidates  capacity  frame bits [dau, cuoi)  truong payload")
    ranges: dict[int, list[int]] = {}
    for placement in placements:
        ranges.setdefault(placement.segment, []).append(placement.frame_bit_index)
    for row in segments["segments"][:session.args.rows]:
        used = ranges.get(row["segment"])
        span = f"[{used[0]:5}, {used[-1] + 1:5})" if used else "  (khong dung)  "
        fields = (f"{deep_trace.frame_field(used[0], message_bytes)} .. {deep_trace.frame_field(used[-1], message_bytes)}"
                  if used else "payload da du truoc segment nay")
        session.say(f" {row['segment']:3}  {row['idr_nal_index']:7}  {row['analysis_nal_index']:12}  "
                    f"{row['candidate_count']:10}  {min(max_bits, row['candidate_count']):8}  {span:22}  {fields}")
    if len(segments["segments"]) > session.args.rows:
        session.say(f"  ... {len(segments['segments']) - session.args.rows} segment nua trong segments_before.json")
