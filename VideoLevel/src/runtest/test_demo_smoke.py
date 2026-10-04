"""Smoke test for the single terminal demo (demo/terminal_demo.py).

Runs ``terminal_demo.py --auto --frames 4 --message smoke`` with the full deep
trace and the native HTTP/WebSocket service steps, then asserts exit code 0,
no ``[FAIL]`` line and ``report.json`` status ``passed``. Skips cleanly when
FFmpeg, Node.js, the native tools, the circuit keys or a sample video are missing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.runtest._helpers import SKIP, run_test, section, summarise

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo" / "terminal_demo.py"
TIMEOUT_SECONDS = 1800
NATIVE_TOOLS = ("zkstego_blind_bits", "zkstego_inspect")
CIRCUIT_FILES = (
    "circuits/build/camera_video.zkey",
    "circuits/build/camera_video_vkey.json",
    "circuits/build/camera_video_js/camera_video.wasm",
    "circuits/build/camera_video_js/generate_witness.js",
    "circuits/node_modules/snarkjs/build/cli.cjs",
)
RUN_FOLDER = re.compile(r"Artifacts \+ transcript \+ report: (.+)$", re.MULTILINE)


def _native_tool_present(name: str) -> bool:
    build = ROOT / "native" / "build"
    return any((folder / f"{name}{suffix}").is_file()
               for folder in (build / "Release", build / "Debug", build) for suffix in (".exe", ""))


def _missing_prerequisite() -> str | None:
    for tool in ("ffmpeg", "ffprobe", "node", "npx"):
        if shutil.which(tool) is None:
            return f"{tool} not found on PATH"
    for name in NATIVE_TOOLS:
        if not _native_tool_present(name):
            return f"native tool {name} not built (run demo/terminal_demo.py --setup)"
    for relative in CIRCUIT_FILES:
        if not (ROOT / relative).is_file():
            return f"circuit artifact missing: {relative} (run demo/terminal_demo.py --setup)"
    for module in ("fastapi", "httpx"):
        if importlib.util.find_spec(module) is None:
            return f"Python package {module} not installed (needed by the service steps)"
    if not any((ROOT / "data" / "raw").glob("*.y4m")) and not any((ROOT / "data").glob("**/*.h264")):
        return "no sample video under data/raw/*.y4m or data/**/*.h264"
    return None


def t_terminal_demo_full_run() -> None:
    reason = _missing_prerequisite()
    if reason:
        SKIP("terminal_demo_full_run", reason)
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, str(DEMO), "--auto", "--frames", "4", "--message", "smoke"],
        cwd=ROOT, env=environment, capture_output=True, timeout=TIMEOUT_SECONDS, check=False,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    tail = (output + result.stderr.decode("utf-8", errors="replace"))[-3000:]
    assert result.returncode == 0, f"demo exit={result.returncode}:\n{tail}"
    assert "[FAIL]" not in output, f"demo printed a [FAIL] check:\n{tail}"
    passes = output.count("[PASS]")
    assert passes > 0, "demo printed no [PASS] check"
    match = RUN_FOLDER.search(output)
    assert match, "demo did not print its run folder"
    report_path = Path(match.group(1).strip()) / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report.get("status") == "passed", f"report.json status = {report.get('status')!r}"
    assert report["checks"] and all(report["checks"].values()), "report.json lists a failed check"
    assert len(report["checks"]) == passes, "report.json and stdout disagree on the number of checks"
    print(
        "DEMO_SMOKE "
        f"checks_passed={passes} max_bits_per_idr={report.get('max_bits_per_idr')} "
        f"idr_segments={report.get('idr_segments')} segments_used={report.get('segments_used')} "
        f"embedded_bits={report.get('embedded_bits')} run_folder={report_path.parent.name}"
    )


def main() -> None:
    section("Demo smoke: terminal_demo.py --auto --frames 4 (deep trace + HTTP/WebSocket)")
    results = [run_test("terminal_demo_full_run", t_terminal_demo_full_run)]
    sys.exit(summarise(results, "Demo smoke"))


if __name__ == "__main__":
    main()
