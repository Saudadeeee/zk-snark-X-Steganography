"""Strict decode validation for reconstructed H.264 output."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.exceptions import UnsupportedStreamError
from src.embedder import (
    _promote_strictly_decoded_candidate,
    _strict_validate_h264_decode,
)


pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


def _encode_baseline(path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1",
            "-frames:v", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-profile:v", "baseline", "-coder", "0", "-g", "1",
            "-f", "h264", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_strict_decode_accepts_valid_baseline_cavlc(tmp_path) -> None:
    video = tmp_path / "valid.h264"
    _encode_baseline(video)

    _strict_validate_h264_decode(str(video))


def test_strict_decode_rejects_invalid_bitstream(tmp_path) -> None:
    video = tmp_path / "invalid.h264"
    video.write_bytes(b"not an H.264 Annex-B stream")

    with pytest.raises(UnsupportedStreamError, match="strict H.264 decode"):
        _strict_validate_h264_decode(str(video))


def test_invalid_candidate_does_not_replace_existing_output(tmp_path) -> None:
    candidate = tmp_path / "candidate.h264"
    output = tmp_path / "output.h264"
    candidate.write_bytes(b"not an H.264 Annex-B stream")
    output.write_bytes(b"previous valid artifact")

    with pytest.raises(UnsupportedStreamError, match="strict H.264 decode"):
        _promote_strictly_decoded_candidate(str(candidate), str(output))

    assert output.read_bytes() == b"previous valid artifact"
    assert candidate.exists()


def test_valid_candidate_is_promoted_after_decode(tmp_path) -> None:
    candidate = tmp_path / "candidate.h264"
    output = tmp_path / "output.h264"
    _encode_baseline(candidate)

    _promote_strictly_decoded_candidate(str(candidate), str(output))

    assert not candidate.exists()
    assert output.exists()
    _strict_validate_h264_decode(str(output))
