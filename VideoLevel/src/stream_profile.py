"""Fail-closed H.264 stream validation for the CAVLC embedding pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .bitstream.bitstream_io import BitstreamReader
from .bitstream.h264 import H264BitstreamParser


BASELINE_PROFILE_IDC = 66
_PROFILE_NAMES = {
    44: "cavlc_444_intra",
    66: "baseline",
    77: "main",
    83: "scalable_baseline",
    86: "scalable_high",
    100: "high",
    110: "high_10",
    122: "high_422",
    244: "high_444_predictive",
}


@dataclass(frozen=True)
class StreamProfile:
    codec: str
    profile: str
    profile_idc: Optional[int]
    entropy_mode: str
    total_vcl_nals: int
    idr_nals: int
    p_slice_nals: int
    inferred_gop_class: str
    is_all_intra: bool
    supported: bool
    rejection_reason: Optional[str] = None


def classify_h264_stream_parameters(*, profile_idc: int, cabac_enabled: bool) -> StreamProfile:
    """Classify SPS/PPS values without trusting caller-provided labels."""
    profile = _PROFILE_NAMES.get(profile_idc, f"profile_{profile_idc}")
    entropy_mode = "cabac" if cabac_enabled else "cavlc"
    if profile_idc != BASELINE_PROFILE_IDC:
        reason = f"unsupported H.264 profile {profile} (profile_idc={profile_idc}); Baseline is required"
    elif cabac_enabled:
        reason = "CABAC entropy coding is unsupported; CAVLC is required"
    else:
        reason = None
    return StreamProfile(
        codec="h264",
        profile=profile,
        profile_idc=profile_idc,
        entropy_mode=entropy_mode,
        total_vcl_nals=0,
        idr_nals=0,
        p_slice_nals=0,
        inferred_gop_class="unknown",
        is_all_intra=False,
        supported=reason is None,
        rejection_reason=reason,
    )


def _parse_pps_cabac_flag(rbsp: bytes) -> bool:
    reader = BitstreamReader(rbsp)
    reader.read_ue()  # pic_parameter_set_id
    reader.read_ue()  # seq_parameter_set_id
    return bool(reader.read_bits(1))  # entropy_coding_mode_flag


def analyze_stream_profile(video_path: str) -> StreamProfile:
    """Parse actual SPS/PPS values and reject missing or malformed headers."""
    parser = H264BitstreamParser(video_path)
    parser.parse()

    profile_idc: Optional[int] = None
    cabac_enabled: Optional[bool] = None
    idr_nals = 0
    p_slice_nals = 0
    total_vcl = 0
    for nal in parser.nal_units:
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7 and profile_idc is None:
            if not nal.rbsp_byte:
                return StreamProfile("h264", "unknown", None, "unknown", 0, 0, 0, "unknown", False, False, "empty SPS")
            profile_idc = int(nal.rbsp_byte[0])
        elif nal_type == 8 and cabac_enabled is None:
            try:
                cabac_enabled = _parse_pps_cabac_flag(nal.rbsp_byte)
            except (ValueError, IndexError, EOFError):
                return StreamProfile("h264", "unknown", profile_idc, "unknown", 0, 0, 0, "unknown", False, False, "malformed PPS")
        elif nal_type == 5:
            idr_nals += 1
            total_vcl += 1
        elif nal_type == 1:
            p_slice_nals += 1
            total_vcl += 1

    if profile_idc is None:
        return StreamProfile("h264", "unknown", None, "unknown", total_vcl, idr_nals, p_slice_nals, "unknown", False, False, "SPS is required")
    if cabac_enabled is None:
        return StreamProfile("h264", _PROFILE_NAMES.get(profile_idc, f"profile_{profile_idc}"), profile_idc, "unknown", total_vcl, idr_nals, p_slice_nals, "unknown", False, False, "PPS is required")

    classified = classify_h264_stream_parameters(profile_idc=profile_idc, cabac_enabled=cabac_enabled)
    is_all_intra = p_slice_nals == 0 and idr_nals > 0
    inferred_gop_class = "all_intra" if is_all_intra else "inter_coded"
    return StreamProfile(
        codec=classified.codec,
        profile=classified.profile,
        profile_idc=classified.profile_idc,
        entropy_mode=classified.entropy_mode,
        total_vcl_nals=total_vcl,
        idr_nals=idr_nals,
        p_slice_nals=p_slice_nals,
        inferred_gop_class=inferred_gop_class,
        is_all_intra=is_all_intra,
        supported=classified.supported,
        rejection_reason=classified.rejection_reason,
    )
