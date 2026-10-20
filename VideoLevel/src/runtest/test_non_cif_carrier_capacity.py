"""Stable carriers must be found across the whole frame at non-CIF resolutions.

Regression: the safety filter mapped macroblocks to IDR frames with the CIF
macroblock count (396), so at any other resolution only the first 396
macroblocks of each frame could be validated and the rest were silently
dropped as unpatchable.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.core.analysis_cache import clear_video_analysis_cache, load_or_build_video_analysis

WIDTH, HEIGHT = 352, 576  # 22 x 36 macroblocks = 792 per frame
MACROBLOCKS_PER_FRAME = (WIDTH // 16) * (HEIGHT // 16)


@pytest.fixture(scope="module")
def tall_clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required")
    path = tmp_path_factory.mktemp("noncif") / "tall.h264"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc2=size={WIDTH}x{HEIGHT}:rate=25,noise=alls=40:allf=t",
         "-frames:v", "2", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1",
         "-bf", "0", "-qp", "22", "-f", "h264", str(path)],
        check=True, timeout=120,
    )
    return path


def test_stable_carriers_cover_rows_beyond_the_cif_macroblock_count(tall_clip) -> None:
    clear_video_analysis_cache()
    safe = load_or_build_video_analysis(tall_clip, use_cache=False, stable_blind_only=True)[5]
    local = [mb % MACROBLOCKS_PER_FRAME for mb, _block, _coefficient in safe]
    assert safe, "no stable carriers found at all"
    beyond = sum(1 for macroblock in local if macroblock >= 396)
    assert beyond > len(local) // 4, (
        f"only {beyond} of {len(local)} carriers lie beyond the first 396 macroblocks"
    )
