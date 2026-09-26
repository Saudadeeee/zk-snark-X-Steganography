"""Tests for the proof-size versus measured in-video capacity gate."""

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from benchmark.lattice_in_video_feasibility import assess_capacity, main
from src.runtest._helpers import run_test, section, summarise


def t_exact_fit_includes_framing_bytes():
    result = assess_capacity(proof_bytes=10, capacity_bits=104, framing_bytes=3)
    assert result.fits
    assert result.required_bits == 104
    assert result.remaining_bits == 0


def t_shortfall_is_reported_in_bits_and_ratio():
    result = assess_capacity(proof_bytes=100, capacity_bits=800, framing_bytes=4)
    assert not result.fits
    assert result.required_bits == 832
    assert result.shortfall_bits == 32
    assert result.required_to_capacity_ratio == 1.04


def t_capacity_is_not_rounded_to_whole_bytes():
    result = assess_capacity(proof_bytes=1, capacity_bits=7)
    assert not result.fits
    assert result.shortfall_bits == 1


def t_rejects_invalid_measurements():
    invalid_values = (
        {"proof_bytes": 0, "capacity_bits": 8},
        {"proof_bytes": 1, "capacity_bits": -1},
        {"proof_bytes": 1, "capacity_bits": 8, "framing_bytes": -1},
        {"proof_bytes": True, "capacity_bits": 8},
    )
    for kwargs in invalid_values:
        try:
            assess_capacity(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"invalid measurement was accepted: {kwargs}")


def _run_cli(capacity_bits: int) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact = Path(temp_dir) / "proof.bin"
        artifact.write_bytes(b"proof-bytes")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "--proof-artifact", str(artifact),
                "--capacity-bits", str(capacity_bits),
                "--framing-bytes", "2",
            ])
    return exit_code, json.loads(stdout.getvalue())


def t_cli_reports_infeasible_status_for_exact_artifact():
    exit_code, report = _run_cli(80)
    assert exit_code == 3
    assert report["proof_bytes"] == 11
    assert report["shortfall_bits"] == 24


def t_cli_succeeds_only_when_capacity_is_enough():
    exit_code, report = _run_cli(104)
    assert exit_code == 0
    assert report["fits"] is True
    assert report["shortfall_bits"] == 0


def main_test():
    section("Phase 12 - Lattice Proof Capacity Gate")
    results = [
        run_test("exact_fit_includes_framing_bytes", t_exact_fit_includes_framing_bytes),
        run_test("shortfall_is_reported_in_bits_and_ratio", t_shortfall_is_reported_in_bits_and_ratio),
        run_test("capacity_is_not_rounded_to_whole_bytes", t_capacity_is_not_rounded_to_whole_bytes),
        run_test("rejects_invalid_measurements", t_rejects_invalid_measurements),
        run_test("cli_reports_infeasible_status_for_exact_artifact", t_cli_reports_infeasible_status_for_exact_artifact),
        run_test("cli_succeeds_only_when_capacity_is_enough", t_cli_succeeds_only_when_capacity_is_enough),
    ]
    raise SystemExit(summarise(results, "Phase 12"))


if __name__ == "__main__":
    main_test()
