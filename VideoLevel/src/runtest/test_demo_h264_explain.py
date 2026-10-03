"""
test_demo_h264_explain.py — the demo's H.264 explanation math must match real decoders.

demo/h264_explain.py recomputes macroblock headers, CAVLC syntax elements, QP,
dequantization, the inverse transform and Intra 4x4 prediction so the deep
terminal demo can print every intermediate value. These tests check that the
recomputation agrees with the native parser (bit offsets, levels) and with
FFmpeg's decoder (pixels before deblocking) on a freshly encoded clip.

Run:
    py -3.12 src/runtest/test_demo_h264_explain.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "demo"))

from src.runtest._helpers import SKIP, run_test, section, summarise  # noqa: E402

import h264_explain as hx  # noqa: E402
from src import h264_tables as cavlc  # noqa: E402

TRACE_TOOL = ROOT / "native" / "build" / "Release" / ("zkstego_inspect.exe" if os.name == "nt" else "zkstego_inspect")
RAW_SOURCE = ROOT / "data" / "raw" / "foreman_cif.y4m"
WIDTH, HEIGHT = 352, 288


def t_inverse_transform_dc_only():
    # A lone DC level spreads evenly: d=64*k -> every residual sample (64k+32)>>6.
    scaled = [[128, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    _, _, residual = hx.inverse_transform(scaled)
    assert residual == [[2] * 4 for _ in range(4)], residual


def t_scan_and_block_index_round_trip():
    assert hx.scan_to_matrix(list(range(16)))[0] == [0, 1, 5, 6]
    for blk in range(16):
        assert hx.block_index(*hx.block_xy(blk)) == blk


def t_dequantize_matches_spec_branches():
    coefficients = [[1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    # qP=28: qP%6=4 -> normAdjust 16, LevelScale 256, shift qP/6-4 = 0.
    assert hx.dequantize(coefficients, 28)[0][0] == 256
    # qP=19: qP%6=1 -> normAdjust 11, LevelScale 176; qP<24 rounds: (176 + 2^0) >> 1.
    assert hx.dequantize(coefficients, 19)[0][0] == (176 + 1) >> 1


def t_fixed_length_coeff_token():
    # nC >= 8: 6-bit code (TotalCoeff-1, TrailingOnes) = (0, 1) -> '000001', sign bit '1',
    # then total_zeros for TotalCoeff=1: '1' -> 0. Eight bits in total.
    rbsp = bytes([0b00000111, 0b10000000])
    block = {"coeff_token_bit": 0, "n_c": 9, "end_bit": 8}
    fields = hx.segment_cavlc_block(rbsp, block, None, 16, cavlc.TOTAL_ZEROS_TABLES, cavlc.RUN_BEFORE_TABLES)
    assert [item.value for item in fields] == [(1, 1), 1, 0], fields


def _encode_and_trace(workdir: Path) -> tuple[Path, dict, bytes]:
    video = workdir / "clip.h264"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(RAW_SOURCE), "-frames:v", "1",
                    "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-qp", "22",
                    "-x264-params", "cabac=0:keyint=1:bframes=0:slices=1:threads=1", "-f", "h264", str(video)],
                   check=True, capture_output=True, timeout=120)
    raw = workdir / "nodeblock.yuv"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-skip_loop_filter", "all", "-i", str(video),
                    "-pix_fmt", "yuv420p", "-f", "rawvideo", str(raw)], check=True, capture_output=True, timeout=120)
    trace = json.loads(subprocess.run([str(TRACE_TOOL), str(video)], check=True, capture_output=True).stdout)
    return video, trace, raw.read_bytes()[:WIDTH * HEIGHT]


def t_recomputed_pixels_and_syntax_match_decoders():
    if not TRACE_TOOL.is_file() or shutil.which("ffmpeg") is None or not RAW_SOURCE.is_file():
        SKIP("recomputed_pixels_and_syntax_match_decoders", "needs zkstego_inspect, ffmpeg and data/raw")
        return
    with tempfile.TemporaryDirectory(prefix="zkstego-explain-") as temp_dir:
        video, trace, plane = _encode_and_trace(Path(temp_dir))
        nal = trace["slices"][0]["nal_index"]

        def detail(address: int) -> dict:
            return json.loads(subprocess.run([str(TRACE_TOOL), str(video), "--macroblock", str(nal), str(address)],
                                             check=True, capture_output=True).stdout)

        first = detail(0)
        rbsp = bytes.fromhex(first["rbsp_hex"])
        macroblocks, mb_width = first["macroblocks"], first["mb_width"]
        for mb in macroblocks:
            reader = hx.TracingBitReader(rbsp, mb["start_bit"])
            header = hx.parse_i_macroblock_header(reader)
            native_cbp = mb["cbp"] & 15 | (min(mb["cbp"] >> 4, 2) << 4)  # native stores chroma CBP 2 as 3
            assert reader.position == mb["residual_bit"] and header["cbp"] == native_cbp, mb["address"]
        modes = hx.derive_intra4x4_modes(macroblocks, mb_width)
        qps = hx.macroblock_qps(macroblocks, first["pic_init_qp"] + first["slice_qp_delta"])
        checked = 0
        for mb in [item for item in macroblocks if item["mb_type"] == 0][:12]:
            blocks = detail(mb["address"])["detail"]["blocks"]
            for block in blocks:
                if not block["coded"]:
                    continue
                n_c = block["n_c"]
                table = (cavlc.COEFF_TOKEN_CHROMA_DC if n_c == -1 else cavlc.COEFF_TOKEN_NC_0_1 if n_c < 2
                         else cavlc.COEFF_TOKEN_NC_2_3 if n_c < 4 else cavlc.COEFF_TOKEN_NC_4_7 if n_c < 8 else None)
                maximum = 4 if block["category"] == "ChromaDC" else 15 if block["category"] == "ChromaAC" else 16
                zeros = cavlc.TOTAL_ZEROS_2x2 if block["category"] == "ChromaDC" else cavlc.TOTAL_ZEROS_TABLES
                fields = hx.segment_cavlc_block(rbsp, block, table, maximum, zeros, cavlc.RUN_BEFORE_TABLES)
                levels = [item.value for item in fields if item.name.startswith("level[")]
                assert levels == block["level_values"], (mb["address"], block["category"], block["index"])
            for blk in range(16):
                block = next(b for b in blocks if b["category"] == "Luma4x4" and b["index"] == blk)
                scan = block["coefficients_scan"] if block["coded"] else [0] * 16
                residual = hx.inverse_transform(hx.dequantize(hx.scan_to_matrix(scan), qps[mb["address"]]))[2]
                neighbours = hx.gather_neighbours(plane, WIDTH, HEIGHT, mb_width, mb["address"], blk)
                predicted = hx.predict_intra4x4(modes[mb["address"]][blk].mode, neighbours)
                bx, by = hx.block_xy(blk)
                x0, y0 = mb["address"] % mb_width * 16 + bx * 4, mb["address"] // mb_width * 16 + by * 4
                actual = [[plane[(y0 + r) * WIDTH + x0 + c] for c in range(4)] for r in range(4)]
                assert hx.clip_add(predicted, residual) == actual, (mb["address"], blk)
                checked += 1
        assert checked > 0, "clip contained no I4x4 macroblocks to check"


def main():
    section("Demo H.264 explanation math")
    results = [
        run_test("inverse_transform_dc_only", t_inverse_transform_dc_only),
        run_test("scan_and_block_index_round_trip", t_scan_and_block_index_round_trip),
        run_test("dequantize_matches_spec_branches", t_dequantize_matches_spec_branches),
        run_test("fixed_length_coeff_token", t_fixed_length_coeff_token),
        run_test("recomputed_pixels_and_syntax_match_decoders", t_recomputed_pixels_and_syntax_match_decoders),
    ]
    sys.exit(summarise(results, "Demo H.264 explain"))


if __name__ == "__main__":
    main()
