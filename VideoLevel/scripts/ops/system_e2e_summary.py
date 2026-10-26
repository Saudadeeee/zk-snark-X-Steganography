"""Summarise a system E2E run (scripts/ops/system_e2e*.sh) into one JSON + a Markdown table.

    python scripts/ops/system_e2e_summary.py --work tmp/system_e2e_v3 \
        --output benchmark/results/q2/system_e2e_check_20261026.json

The per-scenario reports are those of ``benchmark.latticezk_video_e2e``; the
summary keeps the fields the handoff documents quote (``verified_from_video_alone``,
``replay_rejected``, ``tamper_rejected``, ``payload_absent_from_output``,
``envelope_bytes``, ``psnr_modified_db``, ``psnr_worst_db``) and the timings.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"unit_tests"}


def _git_commit() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        return commit + ("+uncommitted" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _unit_tests(work: Path) -> dict[str, Any] | None:
    log = work / "unit_tests.log"
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8", errors="replace")
    match = re.findall(r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?", text)
    if not match:
        return {"log": str(log), "summary": text.strip().splitlines()[-1] if text.strip() else ""}
    passed, failed, skipped = match[-1]
    return {"passed": int(passed), "failed": int(failed or 0), "skipped": int(skipped or 0)}


def _scenario(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    quality = report.get("frame_quality") or {}
    decoded = report.get("decoded_quality") or {}
    linkage = report.get("credential_linkage") or {}
    trailing = report.get("trailing_rbsp_zero_tamper")
    adaptive = report.get("adaptive_chunking")
    return {
        "scenario": path.stem,
        "parameter_set": report.get("parameter_set"),
        "mode": report.get("mode"),
        "carrier_contract": report.get("carrier_contract"),
        "codec_policy": report.get("codec_policy"),
        "gop_policy": report.get("gop_policy"),
        "payload_range_bytes": report.get("payload_range_bytes"),
        "envelope_bytes": report.get("envelope_bytes"),
        "expected_envelope_bytes": report.get("expected_envelope_bytes"),
        "segments_used": report.get("segments_used"),
        "carriers_used": report.get("carriers_used"),
        "verified_from_video_alone": report.get("blind_video_only_verification"),
        "replay_rejected": report.get("replay_rejected"),
        "tamper_rejected": report.get("tamper_rejected"),
        "payload_absent_from_output": report.get("payload_absent_from_output"),
        "p_slice_tamper_rejected": report.get("p_slice_tamper_rejected"),
        "trailing_rbsp_zero_rejected": None if not isinstance(trailing, dict) else trailing.get("rejected"),
        "adaptive_checks": None if not isinstance(adaptive, dict) else adaptive.get("checks"),
        "credential_linkage": linkage or None,
        "frames": quality.get("frames"),
        "frames_modified": quality.get("frames_modified"),
        "psnr_modified_db": quality.get("luma_psnr_modified_frames_db"),
        "psnr_all_db": quality.get("luma_psnr_all_frames_db"),
        "psnr_worst_db": quality.get("luma_psnr_worst_frame_db"),
        "ssim_all": decoded.get("ssim_all"),
        "timings_s": report.get("timings_s"),
    }


def _yes(value: Any) -> str:
    return "--" if value is None else ("yes" if value else "NO")


def markdown(scenarios: list[dict[str, Any]]) -> str:
    lines = [
        "| Scenario | Mode | Codec | Envelope (B) | Segments | Verified | Replay rej. | Tamper rej. "
        "| PSNR mod. (dB) | Worst (dB) | SSIM | Embed (s) | Verify (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scenarios:
        timings = s.get("timings_s") or {}
        codec = "v2" if "sha256-v2" in (s.get("codec_policy") or "") else (
            "cabac" if "cabac" in (s.get("codec_policy") or "") else "v1")
        mode = "registered" if (s.get("mode") or "").startswith("registered") else "in-band"
        if s.get("payload_range_bytes"):
            mode += f" + range L={s['payload_range_bytes']}"
        lines.append(
            f"| {s['scenario']} | {mode} | {codec} | {s.get('envelope_bytes')} | {s.get('segments_used')} "
            f"| {_yes(s.get('verified_from_video_alone'))} | {_yes(s.get('replay_rejected'))} "
            f"| {_yes(s.get('tamper_rejected'))} | {s.get('psnr_modified_db')} | {s.get('psnr_worst_db')} "
            f"| {s.get('ssim_all')} | {(timings.get('embed_s') or 0):.0f} | {(timings.get('verify_s') or 0):.0f} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, default=ROOT / "tmp" / "system_e2e_v3")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--description", default="functional end-to-end check of every system mode")
    arguments = parser.parse_args()
    reports = sorted(p for p in arguments.work.glob("*.json") if p.stem not in SKIP)
    scenarios = [_scenario(p) for p in reports]
    summary = {
        "description": arguments.description,
        "date": date.today().isoformat(),
        "code_commit": _git_commit(),
        "work_dir": str(arguments.work),
        "unit_tests": _unit_tests(arguments.work),
        "all_verified": all(s["verified_from_video_alone"] for s in scenarios) if scenarios else None,
        "all_replay_rejected": all(s["replay_rejected"] in (True, None) for s in scenarios),
        "all_tamper_rejected": all(s["tamper_rejected"] in (True, None) for s in scenarios),
        "scenarios": scenarios,
    }
    text = json.dumps(summary, indent=2, sort_keys=False) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(markdown(scenarios) + "\n")
    sys.stdout.write(f"\nunit_tests: {summary['unit_tests']}  commit: {summary['code_commit']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
