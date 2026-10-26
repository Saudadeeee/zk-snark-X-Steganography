"""SPS, PPS and I-slice header parsing for Main/High profile CABAC streams.

Only what the CABAC I-slice layer needs is kept; every field before the slice
data is parsed so the header's exact bit length is known.  Unsupported
features (interlace, MBAFF, non-4:2:0, bit depth > 8, lossless transform
bypass, slice groups) raise :class:`UnsupportedStream`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HIGH_PROFILES = frozenset({100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135})
SUPPORTED_PROFILES = frozenset({77, 100})  # Main, High
_NEEDS_ESCAPE = re.compile(rb"\x00\x00(?=[\x00-\x03])")

NAL_SLICE_NON_IDR = 1
NAL_SLICE_IDR = 5
NAL_SPS = 7
NAL_PPS = 8

# Pinned decoder bounds (denial-of-service hardening; see docs/CABAC_SUPPORT.md).
# An SPS can declare a picture of up to 2^32 x 2^32 macroblocks and a slice is
# only bounded by the picture, so without these caps a few crafted bytes make
# the pure-Python decoder walk millions of macroblocks.  The caps are the
# Level 6.2 limits of Annex A (MaxFS = 139 264 MBs, 8192 luma samples a side).
MAX_WIDTH_MBS = 512  # 8192 / 16
MAX_HEIGHT_MBS = 512
MAX_MBS_PER_PICTURE = 139_264
MAX_NAL_BYTES = 64 * 1024 * 1024
# Spec ranges of the SPS fields that size later reads (7.4.2.1.1); a crafted
# value outside them would otherwise drive a read loop of up to 2^32 bits.
_MAX_LOG2_MINUS4 = 12  # log2_max_frame_num_minus4, log2_max_pic_order_cnt_lsb_minus4
_MAX_POC_CYCLE = 255  # num_ref_frames_in_pic_order_cnt_cycle


class UnsupportedStream(ValueError):
    """The stream uses an H.264 feature outside the supported CABAC subset."""


def require_picture_geometry(width_mbs: int, height_mbs: int) -> int:
    """Return ``width_mbs * height_mbs`` after checking the pinned geometry caps."""
    if not 1 <= width_mbs <= MAX_WIDTH_MBS or not 1 <= height_mbs <= MAX_HEIGHT_MBS:
        raise ValueError(
            f"picture size {width_mbs}x{height_mbs} macroblocks exceeds the pinned limit "
            f"of {MAX_WIDTH_MBS}x{MAX_HEIGHT_MBS}"
        )
    mbs_per_picture = width_mbs * height_mbs
    if mbs_per_picture > MAX_MBS_PER_PICTURE:
        raise ValueError(
            f"picture of {mbs_per_picture} macroblocks exceeds the pinned limit of {MAX_MBS_PER_PICTURE}"
        )
    return mbs_per_picture


def require_nal_size(nal: bytes) -> None:
    if len(nal) > MAX_NAL_BYTES:
        raise ValueError(f"NAL unit of {len(nal)} bytes exceeds the pinned limit of {MAX_NAL_BYTES}")


def unescape(payload: bytes) -> bytes:
    """Remove emulation prevention bytes (NAL payload after the header byte -> RBSP)."""
    return payload.replace(b"\x00\x00\x03", b"\x00\x00")


def escape(rbsp: bytes) -> bytes:
    """Minimal emulation prevention; a trailing 0x00 (cabac_zero_word) gets a final 0x03."""
    escaped = _NEEDS_ESCAPE.sub(b"\x00\x00\x03", rbsp)
    if rbsp.endswith(b"\x00"):
        escaped += b"\x03"  # 7.4.1: RBSP ending in cabac_zero_word
    return escaped


def is_canonically_escaped(payload: bytes) -> bool:
    return escape(unescape(payload)) == payload


class BitReader:
    """MSB-first reader with Exp-Golomb helpers."""

    __slots__ = ("data", "end", "pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos
        self.end = len(data) * 8

    def u1(self) -> int:
        if self.pos >= self.end:
            raise ValueError("truncated syntax")
        bit = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return bit

    def u(self, width: int) -> int:
        value = 0
        for _ in range(width):
            value = (value << 1) | self.u1()
        return value

    def ue(self) -> int:
        zeros = 0
        while not self.u1():
            zeros += 1
            if zeros > 31:
                raise ValueError("malformed Exp-Golomb code")
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self) -> int:
        code = self.ue()
        return (code + 1) // 2 if code & 1 else -(code // 2)

    def more_rbsp_data(self) -> bool:
        """True while a 1 bit other than the rbsp_stop_one_bit remains."""
        last = self.end - 1
        while last >= 0 and not (self.data[last >> 3] >> (7 - (last & 7))) & 1:
            last -= 1
        return self.pos < last

    @property
    def byte_aligned(self) -> bool:
        return self.pos & 7 == 0


def _skip_scaling_list(reader: BitReader, size: int) -> None:
    last, nxt = 8, 8
    for _ in range(size):
        if nxt:
            nxt = (last + reader.se() + 256) % 256
        last = last if nxt == 0 else nxt


@dataclass(frozen=True)
class SpsInfo:
    sps_id: int
    profile_idc: int
    width_mbs: int
    height_mbs: int
    log2_max_frame_num: int
    poc_type: int
    log2_max_poc_lsb: int
    delta_pic_order_always_zero: int

    @property
    def mbs_per_picture(self) -> int:
        return self.width_mbs * self.height_mbs


def parse_sps(rbsp: bytes) -> SpsInfo:
    reader = BitReader(rbsp)
    profile_idc = reader.u(8)
    reader.u(16)  # constraint flags, level_idc
    sps_id = reader.ue()
    if profile_idc not in SUPPORTED_PROFILES:
        raise UnsupportedStream(f"profile_idc {profile_idc} is not Main (77) or High (100)")
    if profile_idc in _HIGH_PROFILES:
        chroma_format_idc = reader.ue()
        if chroma_format_idc != 1:
            raise UnsupportedStream("only 4:2:0 chroma (chroma_format_idc = 1) is supported")
        if reader.ue() or reader.ue():
            raise UnsupportedStream("only 8-bit luma and chroma are supported")
        if reader.u1():
            raise UnsupportedStream("qpprime_y_zero_transform_bypass_flag is not supported")
        if reader.u1():  # seq_scaling_matrix_present_flag
            for index in range(8):
                if reader.u1():
                    _skip_scaling_list(reader, 16 if index < 6 else 64)
    log2_max_frame_num_minus4 = reader.ue()
    if log2_max_frame_num_minus4 > _MAX_LOG2_MINUS4:
        raise ValueError(f"log2_max_frame_num_minus4 {log2_max_frame_num_minus4} out of range")
    log2_max_frame_num = log2_max_frame_num_minus4 + 4
    poc_type = reader.ue()
    log2_max_poc_lsb = 0
    delta_always_zero = 0
    if poc_type == 0:
        log2_max_poc_lsb_minus4 = reader.ue()
        if log2_max_poc_lsb_minus4 > _MAX_LOG2_MINUS4:
            raise ValueError(f"log2_max_pic_order_cnt_lsb_minus4 {log2_max_poc_lsb_minus4} out of range")
        log2_max_poc_lsb = log2_max_poc_lsb_minus4 + 4
    elif poc_type == 1:
        delta_always_zero = reader.u1()
        reader.se()
        reader.se()
        cycle = reader.ue()
        if cycle > _MAX_POC_CYCLE:
            raise ValueError(f"num_ref_frames_in_pic_order_cnt_cycle {cycle} out of range")
        for _ in range(cycle):
            reader.se()
    elif poc_type != 2:
        raise UnsupportedStream(f"invalid pic_order_cnt_type {poc_type}")
    reader.ue()  # max_num_ref_frames
    reader.u1()  # gaps_in_frame_num_value_allowed_flag
    width_mbs = reader.ue() + 1
    height_mbs = reader.ue() + 1
    require_picture_geometry(width_mbs, height_mbs)
    if not reader.u1():
        raise UnsupportedStream("interlaced H.264 (frame_mbs_only_flag = 0, field or MBAFF) is not supported")
    return SpsInfo(sps_id, profile_idc, width_mbs, height_mbs, log2_max_frame_num, poc_type,
                   log2_max_poc_lsb, delta_always_zero)


@dataclass(frozen=True)
class PpsInfo:
    pps_id: int
    sps_id: int
    entropy_coding_mode: int
    bottom_field_pic_order_in_frame_present: int
    pic_init_qp: int
    deblocking_filter_control_present: int
    redundant_pic_cnt_present: int
    transform_8x8_mode: int


def parse_pps(rbsp: bytes) -> PpsInfo:
    reader = BitReader(rbsp)
    pps_id = reader.ue()
    sps_id = reader.ue()
    entropy = reader.u1()
    bottom_field = reader.u1()
    if reader.ue():
        raise UnsupportedStream("flexible macroblock ordering (slice groups) is not supported")
    reader.ue()
    reader.ue()  # num_ref_idx_l0/l1_default_active_minus1
    reader.u1()  # weighted_pred_flag
    reader.u(2)  # weighted_bipred_idc
    pic_init_qp = 26 + reader.se()
    reader.se()  # pic_init_qs_minus26
    reader.se()  # chroma_qp_index_offset
    deblocking = reader.u1()
    reader.u1()  # constrained_intra_pred_flag
    redundant = reader.u1()
    transform_8x8 = 0
    if reader.more_rbsp_data():
        transform_8x8 = reader.u1()
        # pic_scaling_matrix_present_flag and second_chroma_qp_index_offset do not
        # change the residual syntax, so they are not parsed further.
    return PpsInfo(pps_id, sps_id, entropy, bottom_field, pic_init_qp, deblocking, redundant,
                   transform_8x8)


@dataclass(frozen=True)
class SliceHeaderInfo:
    first_mb: int
    slice_type: int
    pps_id: int
    slice_qp: int
    header_bits: int  # bits of the RBSP before cabac_alignment_one_bit


def parse_i_slice_header(rbsp: bytes, nal_type: int, nal_ref_idc: int,
                         sps_map: dict[int, SpsInfo], pps_map: dict[int, PpsInfo],
                         ) -> tuple[SliceHeaderInfo, SpsInfo, PpsInfo]:
    """Parse an I slice header up to the start of ``slice_data`` (alignment excluded)."""
    reader = BitReader(rbsp)
    first_mb = reader.ue()
    slice_type = reader.ue()
    if slice_type % 5 != 2:
        raise UnsupportedStream(f"slice_type {slice_type} is not an I slice")
    pps_id = reader.ue()
    if pps_id not in pps_map:
        raise ValueError(f"slice refers to unknown PPS {pps_id}")
    pps = pps_map[pps_id]
    if pps.sps_id not in sps_map:
        raise ValueError(f"PPS refers to unknown SPS {pps.sps_id}")
    sps = sps_map[pps.sps_id]
    if not pps.entropy_coding_mode:
        raise UnsupportedStream("slice uses CAVLC; the CABAC parser needs entropy_coding_mode_flag = 1")
    reader.u(sps.log2_max_frame_num)  # frame_num
    if nal_type == NAL_SLICE_IDR:
        reader.ue()  # idr_pic_id
    if sps.poc_type == 0:
        reader.u(sps.log2_max_poc_lsb)
        if pps.bottom_field_pic_order_in_frame_present:
            reader.se()
    elif sps.poc_type == 1 and not sps.delta_pic_order_always_zero:
        reader.se()
        if pps.bottom_field_pic_order_in_frame_present:
            reader.se()
    if pps.redundant_pic_cnt_present:
        if reader.ue():
            raise UnsupportedStream("redundant pictures are not supported")
    if nal_ref_idc:
        if nal_type == NAL_SLICE_IDR:
            reader.u1()  # no_output_of_prior_pics_flag
            reader.u1()  # long_term_reference_flag
        elif reader.u1():  # adaptive_ref_pic_marking_mode_flag
            while True:
                operation = reader.ue()
                if operation == 0:
                    break
                if operation in (1, 3):
                    reader.ue()
                if operation == 2:
                    reader.ue()
                if operation in (3, 6):
                    reader.ue()
                if operation == 4:
                    reader.ue()
    slice_qp = pps.pic_init_qp + reader.se()
    if not 0 <= slice_qp <= 51:
        raise ValueError(f"SliceQPY {slice_qp} out of range")
    if pps.deblocking_filter_control_present:
        if reader.ue() != 1:
            reader.se()
            reader.se()
    if first_mb >= sps.mbs_per_picture:
        raise ValueError("first_mb_in_slice lies outside the picture")
    return SliceHeaderInfo(first_mb, slice_type, pps_id, slice_qp, reader.pos), sps, pps
