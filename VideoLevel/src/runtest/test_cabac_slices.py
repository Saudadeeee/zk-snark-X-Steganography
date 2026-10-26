"""CABAC IDR slices of real libx264 streams: parse, canonical re-encode, carrier edits, FFmpeg decode.

libx264 ends its arithmetic code with a frame-dependent flush pattern instead of
the 9.3.4 EncodeFlush, so a libx264 slice and its canonical re-encoding agree on
every byte except the final one (both decode to the same syntax).  The
canonical form is exactly reproduced: re-encoding it is the identity.
"""

from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

import pytest

from src.bitstream.cabac import (
    AnnexBUnit, UnsupportedStream, collect_parameter_sets, decode_slice, encode_slice, join_annexb,
    split_annexb,
)
from src.bitstream.cabac.syntax import I_PCM, Macroblock
from src.runtest.cabac_media import cabac_clip, psnr_y, strict_decode_errors
from src.transport.cabac_sync import CabacMagnitudeContract, _analyze, inspect_cabac_segment

CLIPS = [
    "foreman_cif_cabac_main_g1_30f.h264",
    "foreman_cif_cabac_high_g1_30f.h264",
    "container_cif_cabac_high_slices4_12f.h264",
    "akiyo_cif_cabac_main_crf18_aq_12f.h264",
    "football_cif_cabac_high_qp4_6f.h264",
]


def _idr_units(path: Path):
    units = split_annexb(path.read_bytes())
    sps, pps = collect_parameter_sets(units)
    return units, sps, pps


@pytest.mark.parametrize("name", CLIPS)
def test_every_idr_slice_decodes_and_reencodes(name) -> None:
    units, sps, pps = _idr_units(cabac_clip(name))
    slices = exact = 0
    decode_time = encode_time = 0.0
    for unit in units:
        if unit.nal_type != 5:
            continue
        slices += 1
        start = time.perf_counter()
        decoded = decode_slice(unit.nal, sps, pps)
        decode_time += time.perf_counter() - start
        start = time.perf_counter()
        canonical = encode_slice(decoded)
        encode_time += time.perf_counter() - start
        assert len(canonical) == len(unit.nal)
        assert canonical[:-1] == unit.nal[:-1], "re-encoding differs before the final byte"
        exact += canonical == unit.nal
        assert (canonical == unit.nal) == decoded.tail_canonical
        # The canonical form is a fixed point and decodes to the same syntax.
        again = decode_slice(canonical, sps, pps)
        assert again.tail_canonical and encode_slice(again) == canonical
        assert sum(len(s.macroblocks) for s in (again,)) == len(decoded.macroblocks)
    assert slices > 0 and exact > 0
    print(f"{name}: {slices} IDR slices, {exact} byte-identical to libx264, "
          f"decode {1000 * decode_time / slices:.0f} ms/slice, encode {1000 * encode_time / slices:.0f} ms/slice")


def _flip(units, sps, pps, rate: float, seed: int) -> tuple[list[AnnexBUnit], int]:
    rng = random.Random(seed)
    out, flips = [], 0
    for unit in units:
        if unit.nal_type != 5:
            out.append(unit)
            continue
        decoded = decode_slice(unit.nal, sps, pps)
        for mb in decoded.macroblocks:
            blocks = [b for b in (mb.luma or []) if b] + [b for b in (mb.luma8x8 or []) if b]
            blocks += [b for comp in (mb.chroma_ac or []) for b in comp if b]
            for block in blocks:
                eligible = [i for i, value in enumerate(block) if abs(value) >= 2]
                if eligible and rng.random() < rate:
                    index = eligible[-1]
                    value = block[index]
                    magnitude = abs(value) ^ 1
                    block[index] = magnitude if value > 0 else -magnitude
                    flips += 1
        out.append(AnnexBUnit(unit.prefix, encode_slice(decoded)))
    return out, flips


@pytest.mark.parametrize("name", CLIPS[:4])
def test_carrier_flips_decode_cleanly_with_high_psnr(tmp_path, name) -> None:
    cover = cabac_clip(name)
    units, sps, pps = _idr_units(cover)
    modified, flips = _flip(units, sps, pps, rate=0.1, seed=7)
    stego = tmp_path / "flipped.h264"
    stego.write_bytes(join_annexb(modified))
    assert flips > 100
    assert strict_decode_errors(stego) == ""
    average, worst = psnr_y(cover, stego)
    print(f"{name}: {flips} flips, PSNR-Y avg {average:.2f} dB, worst frame {worst:.2f} dB")
    assert average >= 35.0
    # Carriers re-derived from the edited stream equal the cover's (invariance under LSB flips).
    contract = CabacMagnitudeContract()
    cover_segment = _analyze(cover.read_bytes(), contract, "all-intra")
    stego_segment = _analyze(stego.read_bytes(), contract, "all-intra")
    assert stego_segment.candidates == cover_segment.candidates


def test_i_pcm_macroblocks_decode_to_their_exact_samples(tmp_path) -> None:
    units, sps, pps = _idr_units(cabac_clip("container_cif_cabac_high_slices4_12f.h264"))
    out, replaced = [], 0
    samples = {}
    for unit in units:
        if unit.nal_type == 5 and replaced < 2:
            decoded = decode_slice(unit.nal, sps, pps)
            for position in (0, 3, len(decoded.macroblocks) - 1):
                old = decoded.macroblocks[position]
                pcm = Macroblock(old.addr)
                pcm.mb_type = I_PCM
                pcm.pcm = bytes((old.addr * 7 + i) % 235 + 16 for i in range(384))
                decoded.macroblocks[position] = pcm
                samples[old.addr] = pcm.pcm
            nal = encode_slice(decoded)
            back = decode_slice(nal, sps, pps)
            assert encode_slice(back) == nal and back.tail_canonical
            assert [mb.pcm for mb in back.macroblocks if mb.mb_type == I_PCM] == [
                mb.pcm for mb in decoded.macroblocks if mb.mb_type == I_PCM
            ]
            out.append(AnnexBUnit(unit.prefix, nal))
            replaced += 1
        else:
            out.append(unit)
    stream = tmp_path / "pcm.h264"
    stream.write_bytes(join_annexb(out))
    assert strict_decode_errors(stream) == ""
    frame = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-i", str(stream), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
        capture_output=True, check=True,
    ).stdout
    width = sps[0].width_mbs * 16
    for addr, pcm in samples.items():
        if addr >= sps[0].mbs_per_picture:
            continue
        x, y = (addr % sps[0].width_mbs) * 16, (addr // sps[0].width_mbs) * 16
        for row in (0, 15):
            start = (y + row) * width + x
            assert frame[start:start + 16] == pcm[row * 16:row * 16 + 16]


def _encode(path: Path, *options: str) -> Path:
    raw = cabac_clip("foreman_cif_cabac_main_g1_30f.h264")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-frames:v", "2",
                    *options, str(path)], check=True, capture_output=True)
    return path


def test_unsupported_streams_are_refused(tmp_path) -> None:
    cavlc = _encode(tmp_path / "cavlc.h264", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1")
    with pytest.raises(UnsupportedStream, match="profile_idc 66"):
        inspect_cabac_segment(cavlc.read_bytes(), "all-intra")
    yuv444 = _encode(tmp_path / "444.h264", "-c:v", "libx264", "-pix_fmt", "yuv444p", "-g", "1")
    with pytest.raises(UnsupportedStream):
        inspect_cabac_segment(yuv444.read_bytes(), "all-intra")
    high10 = _encode(tmp_path / "hi10.h264", "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-g", "1")
    with pytest.raises(UnsupportedStream):
        inspect_cabac_segment(high10.read_bytes(), "all-intra")
    interlaced = _encode(tmp_path / "tff.h264", "-c:v", "libx264", "-profile:v", "main", "-g", "1",
                         "-flags", "+ildct+ilme", "-x264-params", "interlaced=1")
    with pytest.raises(UnsupportedStream, match="interlaced"):
        inspect_cabac_segment(interlaced.read_bytes(), "all-intra")


def test_gop_stream_needs_the_inter_raw_policy() -> None:
    data = cabac_clip("foreman_cif_cabac_high_g8_48f.h264").read_bytes()
    with pytest.raises(ValueError, match="non-IDR slice in an all-intra"):
        inspect_cabac_segment(data, "all-intra")
    structure = inspect_cabac_segment(data, "idr-carriers-inter-raw-v1")
    assert structure.pictures == 48 and structure.idr_slices == 6
    assert structure.non_idr_slices == 42
