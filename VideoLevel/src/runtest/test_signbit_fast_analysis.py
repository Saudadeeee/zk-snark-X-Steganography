"""The fast trailing-one sign analysis must select exactly the checked positions.

Two shortcuts are tested against the slow reference on a real encoded clip:

* ``signbit_only`` skips the magnitude-carrier pass;
* sign flips of genuine trailing ones are accepted without re-encoding the
  block per position (the flag is one raw bit; no other syntax depends on it).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.bitstream.h264 import H264BitstreamParser
from src.core.analysis_cache import _build_reconstruction_context
from src.core.pipeline import extract_all_idr_blocks
from src.core.stego import CAVLCSafetyFilter
from src.exceptions import SafetyFilterError


@pytest.fixture(scope="module")
def analysed(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required")
    path = tmp_path_factory.mktemp("signbit") / "clip.h264"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=352x288:rate=25,noise=alls=30:allf=t",
         "-frames:v", "2", "-c:v", "libx264", "-profile:v", "baseline", "-g", "1",
         "-bf", "0", "-qp", "26", "-f", "h264", str(path)],
        check=True, timeout=120,
    )
    parser = H264BitstreamParser(str(path))
    parser.parse()
    coefficients, frame_data, n_c, nal_lengths, t1_overrides = extract_all_idr_blocks(
        str(path), BitstreamReconstructor(), parser=parser
    )
    context = _build_reconstruction_context(path, parser=parser)
    options = dict(nC_map=n_c, nal_length_map=nal_lengths, t1_override_map=t1_overrides,
                   frame_verified_data=frame_data, cif_mb_count=int(context["mb_count_per_slice"]))
    return coefficients, options


def test_fast_sign_acceptance_matches_per_position_verification(analysed) -> None:
    coefficients, options = analysed
    checked = CAVLCSafetyFilter().get_safe_positions(
        coefficients, signbit_only=True, verify_each_sign=True, **options)
    fast = CAVLCSafetyFilter().get_safe_positions(coefficients, signbit_only=True, **options)
    assert len(fast) > 100
    assert fast == checked


def test_signbit_only_returns_exactly_the_sign_positions_of_the_full_pass(analysed) -> None:
    coefficients, options = analysed
    full = CAVLCSafetyFilter().get_safe_positions(coefficients, **options)
    signs = CAVLCSafetyFilter().get_safe_positions(coefficients, signbit_only=True, **options)
    assert all(position[2] < 0 for position in signs)
    assert sorted(signs) == sorted(position for position in full if position[2] < 0)


def test_signbit_only_and_stable_carriers_are_exclusive(analysed) -> None:
    coefficients, options = analysed
    with pytest.raises(SafetyFilterError):
        CAVLCSafetyFilter().get_safe_positions(
            coefficients, signbit_only=True, stable_carriers_only=True, **options)
