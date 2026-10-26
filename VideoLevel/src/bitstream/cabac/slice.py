"""Decode a CABAC IDR slice NAL unit into syntax and re-encode it canonically.

The slice header bits are carried verbatim; the slice data is decoded with
``syntax.code_macroblock`` and re-encoded by the same traversal.  The
*canonical* NAL unit of a slice is ``encode_slice(decode_slice(nal))``: header
bits, cabac_alignment_one_bits, the 9.3.4 arithmetic code ending with
EncodeFlush (whose last bit is rbsp_stop_one_bit), rbsp_alignment_zero_bits,
the slice's cabac_zero_words, minimal emulation prevention.
"""

from __future__ import annotations

from dataclasses import dataclass

from .engine import BitWriter, CabacDecoder, CabacEncoder, CabacError
from .headers import (
    NAL_SLICE_IDR,
    PpsInfo,
    SpsInfo,
    escape,
    parse_i_slice_header,
    require_nal_size,
    require_picture_geometry,
    unescape,
)
from .syntax import Macroblock, code_macroblock


@dataclass
class CabacSlice:
    """One decoded I slice: everything needed to re-encode it."""

    nal_header: int
    rbsp: bytes  # original RBSP, used only for the verbatim header bits
    header_bits: int
    first_mb: int
    slice_qp: int
    width_mbs: int
    mbs_per_picture: int
    transform_8x8_mode: int
    macroblocks: list[Macroblock]
    zero_words: int
    tail_canonical: bool  # trailing bits/bytes are exactly the canonical form

    def copy(self) -> CabacSlice:
        return CabacSlice(
            self.nal_header, self.rbsp, self.header_bits, self.first_mb, self.slice_qp,
            self.width_mbs, self.mbs_per_picture, self.transform_8x8_mode,
            [mb.copy() for mb in self.macroblocks], self.zero_words, self.tail_canonical,
        )


def _bit(data: bytes, pos: int) -> int:
    return (data[pos >> 3] >> (7 - (pos & 7))) & 1


def _walk(engine, slice_: CabacSlice | None, first_mb: int, width: int, total: int,
          transform_8x8_mode: int) -> list[Macroblock]:
    """Code the macroblocks of one slice; at most ``total - first_mb`` are ever decoded.

    ``total`` must be a pinned-cap picture size (:func:`require_picture_geometry`)
    so a crafted slice cannot keep the decoder running past a real picture.
    """
    if width < 1 or total % width:
        raise ValueError(f"picture of {total} macroblocks is not a whole number of {width}-macroblock rows")
    require_picture_geometry(width, total // width)
    if not 0 <= first_mb < total:
        raise ValueError("first_mb_in_slice lies outside the picture")
    by_addr: dict[int, Macroblock] = {}
    result: list[Macroblock] = []
    previous: Macroblock | None = None
    addr = first_mb
    source = None if slice_ is None else slice_.macroblocks
    index = 0
    while True:
        left = by_addr.get(addr - 1) if addr % width else None
        top = by_addr.get(addr - width)
        current = None
        if source is not None:
            current = source[index]
            if current.addr != addr:
                raise ValueError("macroblock addresses are not consecutive")
        mb = code_macroblock(engine, current, addr, left, top, previous, transform_8x8_mode)
        by_addr[addr] = mb
        result.append(mb)
        previous = mb
        index += 1
        if source is None:
            if engine.terminate():
                return result
        else:
            last = index == len(source)
            engine.terminate(1 if last else 0)
            if last:
                return result
        addr += 1
        if addr >= total:
            # Also the per-NAL decode budget: never more macroblocks than the picture holds.
            raise CabacError("slice data runs past the end of the picture")


def decode_slice(nal: bytes, sps_map: dict[int, SpsInfo], pps_map: dict[int, PpsInfo]) -> CabacSlice:
    """Decode an IDR slice NAL unit (header byte first, emulation prevention included)."""
    if not nal or nal[0] & 0x1F != NAL_SLICE_IDR:
        raise ValueError("not an IDR slice NAL unit")
    require_nal_size(nal)
    rbsp = unescape(nal[1:])
    header, sps, pps = parse_i_slice_header(rbsp, NAL_SLICE_IDR, (nal[0] >> 5) & 3, sps_map, pps_map)
    pos = header.header_bits
    while pos & 7:
        if not _bit(rbsp, pos):
            raise CabacError("cabac_alignment_one_bit is not one")
        pos += 1
    decoder = CabacDecoder(rbsp, pos, header.slice_qp)
    macroblocks = _walk(decoder, None, header.first_mb, sps.width_mbs, sps.mbs_per_picture,
                        pps.transform_8x8_mode)
    end = decoder.pos
    canonical = _bit(rbsp, end - 1) == 1
    while end & 7:
        canonical = canonical and not _bit(rbsp, end)
        end += 1
    tail = rbsp[end >> 3:]
    zero_words = 0
    if tail and not tail.strip(b"\x00") and len(tail) % 2 == 0:
        zero_words = len(tail) // 2
    elif tail:
        canonical = False
    return CabacSlice(
        nal[0], rbsp, header.header_bits, header.first_mb, header.slice_qp, sps.width_mbs,
        sps.mbs_per_picture, pps.transform_8x8_mode, macroblocks, zero_words, canonical,
    )


def encode_slice(slice_: CabacSlice) -> bytes:
    """Canonical NAL unit bytes (header byte first) of ``slice_``."""
    writer = BitWriter()
    for pos in range(slice_.header_bits):
        writer.write(_bit(slice_.rbsp, pos))
    while not writer.aligned:
        writer.write(1)  # cabac_alignment_one_bit
    encoder = CabacEncoder(writer, slice_.slice_qp)
    _walk(encoder, slice_, slice_.first_mb, slice_.width_mbs, slice_.mbs_per_picture,
          slice_.transform_8x8_mode)
    while not writer.aligned:
        writer.write(0)  # rbsp_alignment_zero_bit
    rbsp = writer.to_bytes() + b"\x00\x00" * slice_.zero_words
    return bytes([slice_.nal_header]) + escape(rbsp)


def is_canonical_slice(nal: bytes, sps_map: dict[int, SpsInfo], pps_map: dict[int, PpsInfo]) -> bool:
    """True when ``nal`` equals the canonical re-encoding of its own syntax."""
    return encode_slice(decode_slice(nal, sps_map, pps_map)) == nal
