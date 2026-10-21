"""GOP-structure policies of the blind carrier transport.

A policy states which coded-slice structure a carrier profile accepts. It is
checked on every transport segment from the raw Annex B bytes, before any
carrier analysis, and it is part of the carrier profile identifier, so a
statement made under one policy never verifies under another.

``ALL_INTRA``
    Every coded slice is an IDR slice (``GOP = 1``). This is the original,
    default policy; profiles that use it keep their earlier identifiers.

``IDR_CARRIERS_INTER_RAW``
    GOP > 1 (Baseline, no B slices): carriers are taken from IDR slices only;
    every other NAL unit, in particular each P slice, is bound byte-exactly by
    the canonical digest (its RBSP and header fields; canonical emulation
    prevention is required, so RBSP equality is NAL byte equality). Every
    transport segment must start with an IDR access unit, so a segment never
    references a picture of another segment.

Both policies reject data-partitioned slices, SP/SI/B slices, arbitrary slice
order, slice groups (FMO), redundant pictures, CABAC, non-Baseline or
interlaced SPS, parameter sets that change inside a segment, pictures mixing
IDR and non-IDR slices, bytes outside NAL units, non-canonical emulation
prevention and a set ``forbidden_zero_bit``. Several slices per picture are accepted; the analysis
gives every coded slice its own picture-sized macroblock slot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ALL_INTRA = "all-intra"
IDR_CARRIERS_INTER_RAW = "idr-carriers-inter-raw-v1"
POLICIES = (ALL_INTRA, IDR_CARRIERS_INTER_RAW)

NAL_SLICE_NON_IDR = 1
NAL_SLICE_IDR = 5
_NAL_SPS, _NAL_PPS = 7, 8
_DATA_PARTITION_TYPES = frozenset({2, 3, 4})
# Slice types after ``% 5``: 0 P, 1 B, 2 I, 3 SP, 4 SI.
_SLICE_P, _SLICE_I = 0, 2
_START_CODE = re.compile(rb"\x00\x00\x01")
_NEEDS_ESCAPE = re.compile(rb"\x00\x00(?=[\x00-\x03])")


@dataclass(frozen=True)
class SegmentStructure:
    """Coded-slice structure of one Annex B segment."""

    coded_slices: int
    pictures: int
    idr_slices: int
    non_idr_slices: int
    p_slices: int


def require_policy(policy: str) -> str:
    if policy not in POLICIES:
        raise ValueError(f"unknown GOP policy {policy!r}; expected one of {POLICIES}")
    return policy


def _require_framed_stream(data: bytes) -> None:
    """Every byte must belong to a start code or a NAL unit the digest binds.

    Bytes before the first start code (other than the zeros of a long start
    code) and start codes without a NAL unit are invisible to the parser.
    """
    first = _START_CODE.search(data)
    if first is None or data[: first.start()].strip(b"\x00"):
        raise ValueError("bytes before the first start code")
    starts = [match.end() for match in _START_CODE.finditer(data)]
    if len(nal_unit_spans(data)) != len(starts):
        raise ValueError("start code without a NAL unit")


def nal_unit_spans(data: bytes) -> list[tuple[int, int]]:
    """``(start, end)`` byte offsets of each NAL unit (header byte first).

    Matches ``NALParser``: the zero before a four-byte start code belongs to
    the start code, every other byte up to the next start code to the NAL.
    """
    starts = [match.end() for match in _START_CODE.finditer(data)]
    spans = []
    for index, start in enumerate(starts):
        if index + 1 < len(starts):
            end = starts[index + 1] - 3
            if end > start and data[end - 1] == 0:
                end -= 1
        else:
            end = len(data)
        if end > start:
            spans.append((start, end))
    return spans


def _nal_payloads(data: bytes) -> list[bytes]:
    return [data[start:end] for start, end in nal_unit_spans(data)]


def _is_canonically_escaped(payload: bytes) -> bool:
    """True when emulation prevention is exactly the minimal escaping of the RBSP.

    The parser strips every ``00 00 03``; without this check a superfluous
    escape byte would change the file but not the RBSP the digest binds.
    """
    rbsp = payload.replace(b"\x00\x00\x03", b"\x00\x00")
    return _NEEDS_ESCAPE.sub(b"\x00\x00\x03", rbsp) == payload


def _read_ue(data: bytes, bit: int) -> tuple[int, int]:
    """Decode one unsigned Exp-Golomb value starting at ``bit``."""
    total = len(data) * 8
    zeros = 0
    while bit < total and not (data[bit >> 3] >> (7 - (bit & 7))) & 1:
        zeros += 1
        bit += 1
        if zeros > 31:
            raise ValueError("malformed Exp-Golomb code in slice header")
    if bit >= total:
        raise ValueError("truncated slice header")
    bit += 1
    value = 0
    for _ in range(zeros):
        if bit >= total:
            raise ValueError("truncated slice header")
        value = (value << 1) | ((data[bit >> 3] >> (7 - (bit & 7))) & 1)
        bit += 1
    return (1 << zeros) - 1 + value, bit


def _read_se(data: bytes, bit: int) -> tuple[int, int]:
    code, bit = _read_ue(data, bit)
    return ((code + 1) // 2 if code & 1 else -(code // 2)), bit


def _read_flag(data: bytes, bit: int) -> tuple[int, int]:
    if bit >= len(data) * 8:
        raise ValueError("truncated parameter set")
    return (data[bit >> 3] >> (7 - (bit & 7))) & 1, bit + 1


def _check_pps(rbsp: bytes) -> None:
    """Reject PPS features the parser and patcher do not model.

    CABAC, slice groups (FMO) and redundant pictures would all make the
    carrier analysis read the slice data differently from a decoder.
    """
    bit = 0
    for _ in range(2):  # pic_parameter_set_id, seq_parameter_set_id
        _, bit = _read_ue(rbsp, bit)
    entropy_coding_mode, bit = _read_flag(rbsp, bit)
    if entropy_coding_mode:
        raise ValueError("CABAC entropy coding is not supported; CAVLC is required")
    _, bit = _read_flag(rbsp, bit)  # bottom_field_pic_order_in_frame_present_flag
    num_slice_groups_minus1, bit = _read_ue(rbsp, bit)
    if num_slice_groups_minus1:
        raise ValueError("flexible macroblock ordering (slice groups) is not supported")
    for _ in range(2):  # num_ref_idx_l0/l1_default_active_minus1
        _, bit = _read_ue(rbsp, bit)
    _, bit = _read_flag(rbsp, bit)  # weighted_pred_flag
    bit += 2  # weighted_bipred_idc
    for _ in range(3):  # pic_init_qp/qs_minus26, chroma_qp_index_offset
        _, bit = _read_se(rbsp, bit)
    for _ in range(2):  # deblocking_filter_control_present, constrained_intra_pred
        _, bit = _read_flag(rbsp, bit)
    redundant_pic_cnt_present, _ = _read_flag(rbsp, bit)
    if redundant_pic_cnt_present:
        raise ValueError("redundant pictures are not supported")


BASELINE_PROFILE_IDC = 66


def _check_sps(rbsp: bytes) -> int:
    """Require a progressive Baseline SPS; return macroblocks per picture.

    Other profiles add fields (chroma format, scaling lists, 8x8 transform in
    the PPS) the parser does not model.
    """
    if len(rbsp) < 4:
        raise ValueError("truncated SPS")
    if rbsp[0] != BASELINE_PROFILE_IDC:
        raise ValueError(f"profile_idc {rbsp[0]} is not Baseline (66)")
    bit = 24
    _, bit = _read_ue(rbsp, bit)  # seq_parameter_set_id
    _, bit = _read_ue(rbsp, bit)  # log2_max_frame_num_minus4
    poc_type, bit = _read_ue(rbsp, bit)
    if poc_type == 0:
        _, bit = _read_ue(rbsp, bit)
    elif poc_type == 1:
        _, bit = _read_flag(rbsp, bit)
        _, bit = _read_se(rbsp, bit)
        _, bit = _read_se(rbsp, bit)
        cycle, bit = _read_ue(rbsp, bit)
        for _ in range(cycle):
            _, bit = _read_se(rbsp, bit)
    _, bit = _read_ue(rbsp, bit)  # max_num_ref_frames
    _, bit = _read_flag(rbsp, bit)  # gaps_in_frame_num_value_allowed_flag
    width_minus1, bit = _read_ue(rbsp, bit)
    height_minus1, bit = _read_ue(rbsp, bit)
    frame_mbs_only, _ = _read_flag(rbsp, bit)
    if not frame_mbs_only:
        raise ValueError("interlaced H.264 (frame_mbs_only_flag=0) is not supported")
    return (width_minus1 + 1) * (height_minus1 + 1)


def _slice_header_prefix(rbsp: bytes) -> tuple[int, int]:
    first_mb, bit = _read_ue(rbsp, 0)
    slice_type, _ = _read_ue(rbsp, bit)
    if slice_type > 9:
        raise ValueError(f"invalid slice_type {slice_type}")
    return first_mb, slice_type % 5


def inspect_segment(path: str | Path, policy: str) -> SegmentStructure:
    """Check one Annex B segment against ``policy``; raise ``ValueError`` if it fails."""
    require_policy(policy)
    data = Path(path).read_bytes()
    _require_framed_stream(data)
    coded = pictures = idr = non_idr = p_slices = 0
    previous_first_mb = -1
    picture_nal_type = None
    macroblocks = 0
    parameter_sets: dict[int, bytes] = {}
    for payload in _nal_payloads(data):
        header = payload[0]
        nal_type = header & 0x1F
        if header & 0x80:
            raise ValueError("NAL unit with forbidden_zero_bit set")
        if not _is_canonically_escaped(payload[1:]):
            raise ValueError("NAL unit with non-canonical emulation prevention")
        if nal_type in _DATA_PARTITION_TYPES:
            raise ValueError("data-partitioned slices are not supported")
        if nal_type in (_NAL_SPS, _NAL_PPS):
            # The analysis uses one SPS/PPS pair per segment; repeated copies
            # (x264 repeats them before every IDR) must be identical.
            if parameter_sets.setdefault(nal_type, payload) != payload:
                raise ValueError("parameter sets change within a transport segment")
            rbsp = payload[1:].replace(b"\x00\x00\x03", b"\x00\x00")
            if nal_type == _NAL_PPS:
                _check_pps(rbsp)
            else:
                macroblocks = _check_sps(rbsp)
            continue
        if nal_type not in (NAL_SLICE_NON_IDR, NAL_SLICE_IDR):
            continue
        if _NAL_SPS not in parameter_sets or _NAL_PPS not in parameter_sets:
            raise ValueError("coded slice before the segment's SPS and PPS")
        rbsp = payload[1:].replace(b"\x00\x00\x03", b"\x00\x00")
        first_mb, slice_type = _slice_header_prefix(rbsp)
        if coded == 0 and nal_type != NAL_SLICE_IDR:
            raise ValueError("transport segment does not start with an IDR slice")
        if first_mb >= macroblocks:
            raise ValueError("first_mb_in_slice lies outside the picture")
        if first_mb == 0:
            pictures += 1
            picture_nal_type = nal_type
        elif coded == 0:
            raise ValueError("transport segment starts in the middle of a picture")
        elif first_mb <= previous_first_mb:
            raise ValueError("arbitrary slice order is not supported")
        elif nal_type != picture_nal_type:
            raise ValueError("a picture mixes IDR and non-IDR slices")
        previous_first_mb = first_mb
        coded += 1
        if nal_type == NAL_SLICE_IDR:
            if slice_type != _SLICE_I:
                raise ValueError("IDR NAL unit with a non-I slice type")
            idr += 1
            continue
        if policy == ALL_INTRA:
            raise ValueError(
                "non-IDR slice in an all-intra carrier profile; use the "
                f"{IDR_CARRIERS_INTER_RAW!r} GOP policy for GOP > 1 streams"
            )
        if slice_type not in (_SLICE_P, _SLICE_I):
            raise ValueError("only I and P slices are supported (no B, SP or SI slices)")
        non_idr += 1
        p_slices += slice_type == _SLICE_P
    if coded == 0:
        raise ValueError("transport segment contains no coded slices")
    return SegmentStructure(coded, pictures, idr, non_idr, p_slices)
