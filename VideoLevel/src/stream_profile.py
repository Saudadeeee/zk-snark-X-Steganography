"""
stream_profile.py - Stream class detection for embedding strategy selection.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bitstream.h264 import H264BitstreamParser


@dataclass
class StreamProfile:
    codec: str
    profile: str
    entropy_mode: str
    total_vcl_nals: int
    idr_nals: int
    p_slice_nals: int
    inferred_gop_class: str
    is_all_intra: bool


def analyze_stream_profile(video_path: str) -> StreamProfile:
    parser = H264BitstreamParser(video_path)
    parser.parse()

    idr_nals = 0
    p_slice_nals = 0
    total_vcl = 0
    for nal in parser.nal_units:
        t = int(nal.nal_unit_type)
        if t == 5:
            idr_nals += 1
            total_vcl += 1
        elif t == 1:
            p_slice_nals += 1
            total_vcl += 1

    is_all_intra = p_slice_nals == 0 and idr_nals > 0
    inferred_gop_class = "all_intra" if is_all_intra else "inter_coded"

    return StreamProfile(
        codec="h264",
        profile="baseline",
        entropy_mode="cavlc",
        total_vcl_nals=total_vcl,
        idr_nals=idr_nals,
        p_slice_nals=p_slice_nals,
        inferred_gop_class=inferred_gop_class,
        is_all_intra=is_all_intra,
    )
