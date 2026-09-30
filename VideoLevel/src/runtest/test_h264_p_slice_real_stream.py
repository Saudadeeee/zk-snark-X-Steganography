import shutil
import subprocess

import pytest

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_real_baseline_p_slices_parse_with_skip_neighbor_context(tmp_path):
    video_path = tmp_path / "testsrc2-baseline-cavlc.h264"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=176x144:rate=5:duration=2",
            "-frames:v",
            "10",
            "-an",
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-preset",
            "medium",
            "-x264-params",
            "cabac=0:bframes=0:ref=1:keyint=10:min-keyint=10:scenecut=0:weightp=0",
            "-f",
            "h264",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    nal_units = H264BitstreamParser(str(video_path)).parse()
    reconstructor = BitstreamReconstructor()
    sps = next(
        reconstructor._parse_sps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 7
    )
    pps = next(
        reconstructor._parse_pps_from_nal(nal)
        for nal in nal_units
        if int(nal.nal_unit_type) == 8
    )
    p_slices = [nal for nal in nal_units if int(nal.nal_unit_type) == 1]

    assert len(p_slices) == 9
    for nal in p_slices:
        parsed = TraceableCAVLCParser().extract_with_offsets(nal, sps, pps)
        assert parsed["parse_trusted"] is True, parsed["parse_integrity_issues"]
        assert parsed["parse_integrity_issues"] == []
