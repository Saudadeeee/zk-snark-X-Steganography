"""Annex B framing helpers for CABAC streams: NAL units, parameter sets, IDR slices."""

from __future__ import annotations

from dataclasses import dataclass

from ...transport.gop_policy import nal_unit_spans
from .headers import (
    NAL_PPS,
    NAL_SPS,
    PpsInfo,
    SpsInfo,
    parse_pps,
    parse_sps,
    require_nal_size,
    unescape,
)


@dataclass(frozen=True)
class AnnexBUnit:
    """A NAL unit and the bytes (start code, leading zeros) that precede it."""

    prefix: bytes
    nal: bytes

    @property
    def nal_type(self) -> int:
        return self.nal[0] & 0x1F


def split_annexb(data: bytes) -> list[AnnexBUnit]:
    """Every byte of ``data`` belongs to exactly one unit's prefix or NAL bytes."""
    spans = nal_unit_spans(data)
    if not spans:
        raise ValueError("no NAL units found")
    units = []
    previous_end = 0
    for start, end in spans:
        nal = data[start:end]
        require_nal_size(nal)
        units.append(AnnexBUnit(data[previous_end:start], nal))
        previous_end = end
    if previous_end != len(data):
        raise ValueError("bytes after the last NAL unit")
    return units


def join_annexb(units: list[AnnexBUnit]) -> bytes:
    return b"".join(unit.prefix + unit.nal for unit in units)


def collect_parameter_sets(units: list[AnnexBUnit]) -> tuple[dict[int, SpsInfo], dict[int, PpsInfo]]:
    """Parse all SPS/PPS; a repeated id must repeat identical bytes."""
    sps_map: dict[int, SpsInfo] = {}
    pps_map: dict[int, PpsInfo] = {}
    raw: dict[tuple[int, int], bytes] = {}
    for unit in units:
        if unit.nal_type not in (NAL_SPS, NAL_PPS):
            continue
        rbsp = unescape(unit.nal[1:])
        if unit.nal_type == NAL_SPS:
            info = parse_sps(rbsp)
            key = (NAL_SPS, info.sps_id)
            sps_map[info.sps_id] = info
        else:
            info = parse_pps(rbsp)
            key = (NAL_PPS, info.pps_id)
            pps_map[info.pps_id] = info
        if raw.setdefault(key, unit.nal) != unit.nal:
            raise ValueError("a parameter set id changes its content within the segment")
    return sps_map, pps_map
