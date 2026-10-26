"""Transcribe the normative H.264 CABAC tables from FFmpeg n7.1 into ``src/bitstream/cabac/tables.py``.

Usage (from VideoLevel/)::

    mkdir ffref
    for f in cabac.c h264_cabac.c; do
      curl -sfL -o ffref/$f https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/libavcodec/$f
    done
    python research/cabac/gen_cabac_tables.py ffref src/bitstream/cabac/tables.py

The script only extracts numbers and checks their structure (duplicated LPS
rows, MPS/LPS state transitions); re-running it must reproduce tables.py
exactly (``test_cabac_engine.py`` pins a digest of the values).
"""
import re
import sys
from pathlib import Path

REF = Path(sys.argv[1])
OUT = Path(sys.argv[2])


def numbers(text: str) -> list[int]:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return [int(v) for v in re.findall(r"-?\d+", text)]


cabac_c = (REF / "cabac.c").read_text()
body = cabac_c.split("ff_h264_cabac_tables)[512 + 4*2*64 + 4*64 + 63] = {", 1)[1].split("};", 1)[0]
packed = numbers(body)
assert len(packed) == 512 + 512 + 256 + 63, len(packed)
lps = [v & 0xFF for v in packed[512:1024]]
mlps = packed[1024:1280]
last8x8 = packed[1280:]

range_lps = [[lps[q * 128 + 2 * p] for q in range(4)] for p in range(64)]
for p in range(64):
    for q in range(4):
        assert lps[q * 128 + 2 * p] == lps[q * 128 + 2 * p + 1]

# FFmpeg state s = 2 * pStateIdx + valMPS; MPS path -> mlps[128 + s], LPS path -> mlps[127 - s].
trans_mps, trans_lps = [], []
for p in range(64):
    s = 2 * p
    nm = mlps[128 + s]
    assert nm & 1 == 0 and mlps[128 + s + 1] == nm + 1
    trans_mps.append(nm >> 1)
    nl = mlps[127 - s]  # LPS with valMPS = 0: new state for (p, mps=0)
    expected_mps = 1 if p == 0 else 0
    assert nl & 1 == expected_mps, (p, nl)
    trans_lps.append(nl >> 1)

h264_cabac = (REF / "h264_cabac.c").read_text()
init_body = h264_cabac.split("cabac_context_init_I[1024][2] =", 1)[1].split("};", 1)[0]
init = numbers(init_body)
assert len(init) == 2048, len(init)
init_i = [(init[2 * i], init[2 * i + 1]) for i in range(1024)]

sig8 = h264_cabac.split("significant_coeff_flag_offset_8x8[2][63] = {", 1)[1].split("};", 1)[0]
sig8 = numbers(sig8)
assert len(sig8) == 126
sig8_frame = sig8[:63]
assert len(last8x8) == 63


def fmt_rows(values, per_line=16, indent="    "):
    lines = []
    for i in range(0, len(values), per_line):
        lines.append(indent + ", ".join(str(v) for v in values[i:i + per_line]) + ",")
    return "\n".join(lines)


out = f'''"""Normative CABAC tables of ITU-T H.264 used for I slices (8-bit 4:2:0, frame coding).

Provenance: transcribed mechanically by ``research/cabac/gen_cabac_tables.py``
from FFmpeg tag n7.1 (commit 507a51fbe9732f0f6f12f43ce12431e8faa834b7),
``libavcodec/cabac.c`` (``ff_h264_cabac_tables``) and ``libavcodec/h264_cabac.c``
(``cabac_context_init_I``, ``significant_coeff_flag_offset_8x8``), which encode:

* Tables 9-12 .. 9-33: (m, n) context initialisation values for I slices
  (``cabac_init_idc`` column "I"), ctxIdx 0..1023;
* Table 9-44: ``rangeTabLPS[pStateIdx][qCodIRangeIdx]``;
* Table 9-45: ``transIdxLPS`` / ``transIdxMPS``;
* Table 9-43: ctxIdxInc of ``significant_coeff_flag`` (frame coded) and of
  ``last_significant_coeff_flag`` for 8x8 luma blocks (ctxBlockCat 5).

The numeric values are normative data of the standard; no FFmpeg code is used.
"""

from __future__ import annotations

# (m, n) for every ctxIdx 0..1023, I slices.  Entries never used by I slices are (0, 0).
INIT_I: tuple[tuple[int, int], ...] = (
{fmt_rows([f"({m}, {n})" for m, n in init_i], per_line=8)}
)

# rangeTabLPS[pStateIdx][qCodIRangeIdx]
RANGE_TAB_LPS: tuple[tuple[int, int, int, int], ...] = (
{fmt_rows(["(" + ", ".join(map(str, row)) + ")" for row in range_lps], per_line=4)}
)

TRANS_IDX_LPS: tuple[int, ...] = (
{fmt_rows(trans_lps)}
)

TRANS_IDX_MPS: tuple[int, ...] = (
{fmt_rows(trans_mps)}
)

# ctxIdxInc of significant_coeff_flag for ctxBlockCat 5, frame coded macroblocks.
SIG_COEFF_FLAG_OFFSET_8X8: tuple[int, ...] = (
{fmt_rows(sig8_frame)}
)

# ctxIdxInc of last_significant_coeff_flag for ctxBlockCat 5.
LAST_COEFF_FLAG_OFFSET_8X8: tuple[int, ...] = (
{fmt_rows(last8x8)}
)
'''
OUT.write_text(out, encoding="utf-8")
print(f"wrote {OUT}")
