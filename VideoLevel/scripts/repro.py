"""Reproduction driver for the lattice-ZK video evaluation (see ARTIFACT.md).

The PowerShell and POSIX wrappers next to this file call one subcommand each:

    python scripts/repro.py unit-tests             # lattice-ZK + touched-module tests
    python scripts/repro.py prepare-data           # verify/download Y4M, encode covers
    python scripts/repro.py small                  # one short registered E2E run
    python scripts/repro.py all                    # the whole evaluation (many hours)

Only the standard library is needed to drive the steps; the steps themselves
need the packages in requirements.lock and ffmpeg/ffprobe on PATH.  Run from
any directory; every path is resolved against the VideoLevel root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "data_manifest.json"
RUNTEST = "src/runtest"
RESULTS = ROOT / "benchmark" / "results" / "q2"
WORK = ROOT / "tmp" / "q2"
PRODUCTION_PARAMETER_SET = "BDLOP_OPEN_128"
PRODUCTION_PARAMETER_NAME = "bdlop-open-128-v1"
DEFAULT_SMALL_VIDEO = "data/encoded/container_cif_q22_g1.h264"
# Chunk size per carrier for the short run: the registered envelope (7 589 B)
# must fit the carriers of the cut.  T1 sign carriers give 470-550 kbit per
# 100 CIF frames, so one 100-frame segment holds it; the magnitude carrier
# gives 10-51 kbit per 100 frames at QP 22 and needs >= 200 frames.
SMALL_CHUNK_BYTES = {"t1": 8000, "magnitude": 3800}

# --------------------------------------------------------------------------- #
# Test selection
# --------------------------------------------------------------------------- #

LATTICE_ZK_PYTEST = (
    "test_latticezk_ring.py",
    "test_latticezk_bdlop.py",
    "test_latticezk_equality.py",
    "test_latticezk_kat.py",
    "test_latticezk_video_proof.py",
    "test_latticezk_video_pipeline.py",
    "test_latticezk_linkage.py",
    "test_latticezk_cli.py",
    "test_latticezk_ml_steganalysis.py",
    "test_latticezk_q2_sweep.py",
)
# Modules the lattice-ZK pipeline changed or depends on directly: carrier
# analysis (analysis_cache, stego, blind_sync), chunk framing, RBSP patching,
# sessions and the relation registry.
TOUCHED_MODULE_PYTEST = (
    "test_non_cif_carrier_capacity.py",
    "test_signbit_fast_analysis.py",
    "test_analysis_cache_bounded.py",
    "test_phase20_analysis_cache_patchability_context.py",
    "test_safe_position_ordering.py",
    "test_rbsp_patch.py",
    "test_blind_payload_chunks.py",
    "test_blind_payload_envelope.py",
    "test_blind_sync_streaming.py",
    "test_blind_stable_analysis.py",
    "test_video_only_blind_sync_integration.py",
    "test_zkp_sessions.py",
    "test_zkp_session_http.py",
)
# Script-style suites print [PASS]/[FAIL] lines; exit 0 = pass, 1 = fail,
# 2 = incomplete (a case was skipped).
SCRIPT_SUITES = (
    "test_lattice_pq_stack.py",
    "test_zkp_registry.py",
    "test_video_zkp_contract.py",
    "test_video_zkp_context_relation.py",
    "test_lattice_zkp.py",
)
COMPILE_TARGETS = ("src/lattice_zk", "research/bdlop_params", "benchmark", "scripts")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _say(message: str) -> None:
    sys.stdout.write(time.strftime("[%H:%M:%S] ") + message + "\n")
    sys.stdout.flush()


def _run(command: Sequence[str], log: Path | None = None) -> int:
    """Run a command from ROOT, streaming its output (and copying it to ``log``)."""
    _say("$ " + " ".join(str(part) for part in command))
    with subprocess.Popen(
        [str(part) for part in command], cwd=ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    ) as process:
        handle = log.open("a", encoding="utf-8") if log is not None else None
        try:
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                if handle is not None:
                    handle.write(line)
            sys.stdout.flush()
        finally:
            if handle is not None:
                handle.close()
        return process.wait()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise SystemExit(f"error: required tool(s) not on PATH: {', '.join(missing)}")


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# unit-tests
# --------------------------------------------------------------------------- #


def _syntax_check() -> int:
    """Compile every Python file of the lattice-ZK code paths in memory (writes no .pyc)."""
    errors = 0
    files = sorted(path for target in COMPILE_TARGETS for path in (ROOT / target).rglob("*.py"))
    for path in files:
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except SyntaxError as error:
            errors += 1
            sys.stdout.write(f"  syntax error: {error}\n")
    _say(f"syntax check: {len(files)} files, {errors} errors")
    return 1 if errors else 0


def unit_tests(arguments: argparse.Namespace) -> int:
    results: list[tuple[str, int]] = [("syntax check (" + ", ".join(COMPILE_TARGETS) + ")", _syntax_check())]
    python = sys.executable

    pytest_files = [f"{RUNTEST}/{name}" for name in LATTICE_ZK_PYTEST + TOUCHED_MODULE_PYTEST]
    command = [python, "-B", "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *pytest_files]
    if arguments.junit_xml:
        command += ["--junit-xml", str(_resolve(arguments.junit_xml))]
    results.append(("pytest (" + str(len(pytest_files)) + " files)", _run(command)))

    for name in SCRIPT_SUITES:
        code = _run([python, "-B", f"{RUNTEST}/{name}"])
        results.append((name, code))

    _say("summary")
    failed = False
    for name, code in results:
        status = {0: "OK", 2: "INCOMPLETE (skipped cases)"}.get(code, f"FAIL (exit {code})")
        failed = failed or code not in (0, 2)
        sys.stdout.write(f"  {status:28s} {name}\n")
    sys.stdout.write("RESULT: " + ("FAIL" if failed else "PASS") + "\n")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# prepare-data
# --------------------------------------------------------------------------- #


def _download(url: str, target: Path) -> None:
    partial = target.with_name(target.name + ".part")
    _say(f"download {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "zkstego-artifact/1"})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as sink:
        shutil.copyfileobj(response, sink, length=1 << 20)
    partial.replace(target)


def _check_source(entry: dict[str, Any], raw: Path, download: bool) -> bool:
    path = raw / entry["name"]
    if not path.exists():
        if not download or not entry.get("url"):
            hint = "pass --download" if entry.get("url") else "no public URL; see ARTIFACT.md"
            _say(f"{'SKIP    ' if entry.get('optional') else 'MISSING '} {path} ({hint})")
            return bool(entry.get("optional"))
        raw.mkdir(parents=True, exist_ok=True)
        _download(entry["url"], path)
    digest = _sha256(path)
    if digest != entry["sha256"]:
        _say(f"BAD HASH {path}: {digest} != {entry['sha256']}")
        return False
    _say(f"OK       {path.name} sha256={digest[:16]}...")
    return True


def _encode_command(entry: dict[str, Any], source: Path, output: Path) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if entry.get("stream_loop"):
        command += ["-stream_loop", str(entry["stream_loop"])]
    command += ["-i", str(source)]
    if entry.get("frames"):
        command += ["-frames:v", str(entry["frames"])]
    command += ["-c:v", "libx264", "-profile:v", "baseline", "-g", "1", "-bf", "0",
                "-qp", str(entry["qp"]), "-threads", str(entry["threads"]), "-f", "h264", str(output)]
    return command


def _check_encode(entry: dict[str, Any], raw: Path, encoded: Path, strict: bool) -> bool:
    output = encoded / entry["name"]
    if not output.exists():
        source = raw / entry["source"]
        if not source.exists():
            _say(f"{'SKIP    ' if entry.get('optional') else 'MISSING '} {source} (needed for {entry['name']})")
            return bool(entry.get("optional"))
        encoded.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(output.name + ".part")
        if _run(_encode_command(entry, source, partial)) != 0:
            partial.unlink(missing_ok=True)
            _say(f"ENCODE FAILED {entry['name']}")
            return False
        partial.replace(output)
    digest, expected = _sha256(output), entry.get("sha256")
    if expected is None:
        _say(f"OK       {output.name} sha256={digest} (no reference hash)")
        return True
    if digest == expected:
        _say(f"OK       {output.name} sha256 matches the reference")
        return True
    if entry.get("reproducible") is False:
        _say(f"WARNING  {output.name}: {digest} != {expected} (known: {entry.get('note', 'not reproducible')})")
        return True
    _say(f"{'BAD HASH' if strict else 'WARNING '} {output.name}: {digest} != {expected} "
         "(different x264 build or thread count changes the SEI; pixels may still match)")
    return not strict


def prepare_data(arguments: argparse.Namespace) -> int:
    manifest = _load_manifest()
    raw, encoded = _resolve(arguments.raw), _resolve(arguments.encoded)
    encodes = manifest["encodes"]
    if arguments.only:
        encodes = [entry for entry in encodes if entry["name"] in arguments.only]
        unknown = set(arguments.only) - {entry["name"] for entry in encodes}
        if unknown:
            raise SystemExit(f"error: unknown encode name(s): {', '.join(sorted(unknown))}")
    needed = {entry["source"] for entry in encodes}
    bad_sources = {entry["name"] for entry in manifest["sources"]
                   if entry["name"] in needed and not _check_source(entry, raw, arguments.download)}
    ok = not bad_sources
    if arguments.no_encode:
        return 0 if ok else 1
    _require_tools("ffmpeg")
    for entry in encodes:
        if entry["source"] in bad_sources:
            _say(f"SKIP     {entry['name']} (source {entry['source']} failed its check)")
            continue
        ok = _check_encode(entry, raw, encoded, arguments.strict_encoded) and ok
    sys.stdout.write("RESULT: " + ("PASS" if ok else "FAIL") + "\n")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# small
# --------------------------------------------------------------------------- #


def _primary_slice_offsets(data: bytes) -> tuple[list[int], list[int]]:
    """Byte offsets of each access unit's first NAL and of each primary slice.

    Annex-B start codes cannot occur inside a NAL (emulation prevention), so a
    scan for ``00 00 01`` finds every NAL.  A slice (type 1 or 5) whose first
    header bit is 1 has ``first_mb_in_slice == 0`` and starts a new picture.
    """
    au_starts, slices, pending, index = [], [], None, data.find(b"\x00\x00\x01")
    while index >= 0 and index + 4 < len(data):
        start = index - 1 if index > 0 and data[index - 1] == 0 else index
        nal_type = data[index + 3] & 0x1F
        if nal_type in (1, 5) and data[index + 4] & 0x80:
            slices.append(start)
            au_starts.append(pending if pending is not None else start)
            pending = None
        elif nal_type in (6, 7, 8, 9) and pending is None and slices:
            pending = start
        elif nal_type in (1, 5):
            pending = None
        index = data.find(b"\x00\x00\x01", index + 3)
    return au_starts, slices


def cut_annexb(source: Path, target: Path, frames: int) -> int:
    """Copy the first ``frames`` pictures of an Annex-B H.264 stream; returns the count."""
    data = source.read_bytes()
    au_starts, _ = _primary_slice_offsets(data)
    end = au_starts[frames] if len(au_starts) > frames else len(data)
    target.write_bytes(data[:end])
    return min(frames, len(au_starts))


def _ffprobe_frames(path: Path) -> int | None:
    if shutil.which("ffprobe") is None:
        return None
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    text = completed.stdout.strip().rstrip(",")
    return int(text) if text.isdigit() else None


@dataclass
class _PeakMemory:
    """Polls the resident set size of a process tree (needs psutil; optional)."""

    pid: int
    peak_bytes: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)

    def start(self) -> "_PeakMemory":
        try:
            import psutil  # noqa: F401
        except ImportError:
            return self
        threading.Thread(target=self._poll, daemon=True).start()
        return self

    def _poll(self) -> None:
        import psutil

        try:
            root = psutil.Process(self.pid)
        except psutil.Error:
            return
        while not self._stop.wait(1.0):
            try:
                processes = [root, *root.children(recursive=True)]
                total = sum(process.memory_info().rss for process in processes)
            except psutil.Error:
                continue
            self.peak_bytes = max(self.peak_bytes, total)

    def stop(self) -> None:
        self._stop.set()


def _run_measured(command: Sequence[str], log: Path) -> tuple[int, float, int]:
    _say("$ " + " ".join(str(part) for part in command))
    started = time.perf_counter()
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen([str(part) for part in command], cwd=ROOT,
                                   stdout=handle, stderr=subprocess.STDOUT)
        monitor = _PeakMemory(process.pid).start()
        code = process.wait()
        monitor.stop()
    return code, time.perf_counter() - started, monitor.peak_bytes


def _check_small_report(report: dict[str, Any], security_checks: bool) -> list[tuple[str, bool]]:
    checks = [
        ("production parameter set " + PRODUCTION_PARAMETER_NAME,
         report.get("parameter_set") == PRODUCTION_PARAMETER_NAME),
        ("registered mode", report.get("mode") == "registered-commitment"),
        ("envelope has the expected size", report.get("envelope_bytes") == report.get("expected_envelope_bytes")),
        ("verified from the stego video alone", report.get("blind_video_only_verification") is True),
        ("payload absent from the stego file", report.get("payload_absent_from_output") is True),
    ]
    if security_checks:
        checks += [("replayed session rejected", report.get("replay_rejected") is True),
                   ("one-bit tampered copy rejected", report.get("tamper_rejected") is True)]
    return checks


def small(arguments: argparse.Namespace) -> int:
    _require_tools("ffmpeg")
    video = _resolve(arguments.video)
    if not video.is_file():
        raise SystemExit(f"error: cover video not found: {video}\n"
                         "       run scripts/prepare_data first or pass --video")
    work = _resolve(arguments.work) / time.strftime("run-%Y%m%d-%H%M%S")
    work.mkdir(parents=True, exist_ok=False)
    cover = work / f"{video.stem}_{arguments.frames}f.h264"
    frames = cut_annexb(video, cover, arguments.frames)
    probed = _ffprobe_frames(cover)
    _say(f"cover cut: {cover} ({frames} pictures; ffprobe: {probed}; sha256 {_sha256(cover)[:16]}...)")
    if frames != arguments.frames or (probed is not None and probed != frames):
        raise SystemExit(f"error: expected {arguments.frames} frames in the cut")

    chunk = arguments.chunk_bytes or SMALL_CHUNK_BYTES[arguments.carrier]
    report_path, stego = work / "e2e_report.json", work / "stego.h264"
    command = [sys.executable, "-B", "-m", "benchmark.latticezk_video_e2e",
               "--video", str(cover), "--output", str(stego), "--report", str(report_path),
               "--parameter-set", PRODUCTION_PARAMETER_SET, "--registered",
               "--carrier", arguments.carrier, "--chunk-bytes", str(chunk)]
    if not arguments.security_checks:
        command.append("--skip-security-checks")
    code, seconds, peak = _run_measured(command, work / "e2e.log")
    _say(f"e2e exit code {code}, wall {seconds:.0f} s, peak RSS "
         + (f"{peak / 2**20:.0f} MiB" if peak else "n/a (psutil missing)"))
    if not report_path.exists():
        sys.stdout.write((work / "e2e.log").read_text(encoding="utf-8", errors="replace")[-4000:])
        sys.stdout.write("RESULT: FAIL (no report)\n")
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = {key: report.get(key) for key in (
        "parameter_set", "mode", "carrier", "carrier_contract", "envelope_bytes", "carriers_used",
        "segments_used", "chunk_bytes", "blind_video_only_verification", "verify_reason",
        "replay_rejected", "tamper_rejected", "payload_absent_from_output", "timings_s")}
    summary["frame_quality"] = {key: (report.get("frame_quality") or {}).get(key) for key in (
        "frames", "frames_modified", "luma_psnr_modified_frames_db", "luma_psnr_worst_frame_db")}
    summary["ssim_all"] = (report.get("decoded_quality") or {}).get("ssim_all")
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    checks = _check_small_report(report, arguments.security_checks)
    for name, passed in checks:
        sys.stdout.write(f"  [{'PASS' if passed else 'FAIL'}] {name}\n")
    passed = code == 0 and all(result for _, result in checks)
    sys.stdout.write(f"report: {report_path}\nRESULT: {'PASS' if passed else 'FAIL'}\n")
    if passed and not arguments.keep:
        stego.unlink(missing_ok=True)
    return 0 if passed else 1


# --------------------------------------------------------------------------- #
# all
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]
    outputs: tuple[Path, ...] = ()   # skipped when every output exists
    always: bool = False             # reports: rerun every time
    requires: tuple[Path, ...] = ()  # skipped (and listed) when an input is missing


def _capacity_steps(python: str) -> list[Step]:
    full = (("container", 18), ("container", 22), ("container", 28), ("city", 22),
            ("coastguard", 22), ("football", 22), ("hall_monitor", 22))
    first = (("akiyo", 22), ("deadline", 22), ("foreman", 22))
    steps = []
    for clip, qp in full:
        out, video = RESULTS / f"capacity_{clip}_q{qp}.json", ROOT / f"data/encoded/{clip}_cif_q{qp}_g1.h264"
        steps.append(Step(f"capacity {clip} q{qp}", (python, "-B", "-m", "benchmark.latticezk_capacity_scan",
                          str(video), "--output", str(out)), (out,), requires=(video,)))
    for clip, qp in first:
        out, video = RESULTS / f"capacity_seg0_{clip}_q{qp}.json", ROOT / f"data/encoded/{clip}_cif_q{qp}_g1.h264"
        steps.append(Step(f"capacity {clip} q{qp} (first segment)", (
            python, "-B", "-m", "benchmark.latticezk_capacity_scan", str(video),
            "--segments", "1", "--output", str(out)), (out,), requires=(video,)))
    return steps


def _evaluation_steps(python: str, workers: int) -> list[Step]:
    ml_cases = ("city_cif_q22_reg", "coastguard_cif_q22_reg", "container_cif_q22_reg",
                "deadline_cif_q22_reg", "hall_cif_q22_reg")
    inband = WORK / "coastguard3000f_q22_inband_link.h264"
    inband_report = RESULTS / "e2e_coastguard3000f_q22_inband_link.json"
    today = time.strftime("%Y%m%d")
    return [
        Step("sweep (all cases)", (python, "-B", "-m", "benchmark.latticezk_q2_sweep", "--cases",
                                   "benchmark/latticezk_q2_cases.json", "--workers", str(workers))),
        Step("in-band + linkage E2E on looped Coastguard", (
            python, "-B", "-m", "benchmark.latticezk_video_e2e", "--video",
            "data/encoded/coastguard_cif_q22_g1_3000f.h264", "--output", str(inband),
            "--report", str(inband_report)), (inband_report,)),
        Step("learned steganalysis (LOCO, 5 CIF clips)", (
            python, "-B", "-m", "benchmark.latticezk_ml_steganalysis", "evaluate",
            *[str(WORK / f"mlfeat_{case}.npz") for case in ml_cases],
            "--output", str(RESULTS / "ml_eval.json")), (RESULTS / "ml_eval.json",)),
        Step("embedding-rule simulation (replacement / matching / T1)", (
            python, "-B", "-m", "benchmark.latticezk_embedding_sim", "--cases", *ml_cases,
            "--output", str(RESULTS / "embedding_t1_vs_magnitude_sim.json")),
            (RESULTS / "embedding_t1_vs_magnitude_sim.json",)),
        Step("density simulation", (
            python, "-B", "-m", "benchmark.latticezk_embedding_sim", "--cases", *ml_cases,
            "--densities", "1", "0.5", "0.25", "0.1",
            "--output", str(RESULTS / "embedding_density_sim.json")), (RESULTS / "embedding_density_sim.json",)),
        Step("baselines (BDLOP, ML-DSA, Groth16 if node/snarkjs exist)", (
            python, "-B", "-m", "benchmark.latticezk_baselines",
            "--output", str(RESULTS / f"baselines_{today}.json")), (RESULTS / f"baselines_{today}.json",)),
        Step("crypto micro-benchmark (50 runs)", (
            python, "-B", "-m", "benchmark.latticezk_crypto_bench", "--runs", "50",
            "--output", str(ROOT / "benchmark" / "results" / f"latticezk_crypto_bench_{today}.json")),
            (ROOT / "benchmark" / "results" / f"latticezk_crypto_bench_{today}.json",)),
        Step("report: tables and figures", (python, "-B", "-m", "benchmark.latticezk_q2_report"), always=True),
        Step("report: carrier comparison", (python, "-B", "-m", "benchmark.latticezk_carrier_compare",
                                            "--output", str(RESULTS / "carrier_compare.md")), always=True),
        Step("report: density", (python, "-B", "-m", "benchmark.latticezk_density_report",
                                 "--output", str(RESULTS / "density_report.json")), always=True),
    ]


def _back_up(path: Path, stamp: str) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        _say(f"--fresh: moving {path} -> {backup}")
        path.rename(backup)


def reproduce_all(arguments: argparse.Namespace) -> int:
    _require_tools("ffmpeg", "ffprobe")
    if arguments.fresh:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        _back_up(RESULTS, stamp)
        _back_up(WORK, stamp)
    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    log = WORK / "reproduce_all.log"
    failures: list[str] = []
    skipped: list[str] = []
    if not arguments.skip_prepare:
        prepare = argparse.Namespace(raw="data/raw", encoded="data/encoded", download=arguments.download,
                                     only=None, no_encode=False, strict_encoded=False)
        if prepare_data(prepare) != 0:
            raise SystemExit("error: data preparation failed; fix it before running the sweep")
    steps = _capacity_steps(sys.executable) + _evaluation_steps(sys.executable, arguments.workers)
    for step in steps:
        if not step.always and step.outputs and all(path.exists() for path in step.outputs):
            _say(f"skip (output exists): {step.name}")
            continue
        missing = [path for path in step.requires if not path.exists()]
        if missing:
            _say(f"skip (missing input {missing[0]}): {step.name}")
            skipped.append(step.name)
            continue
        _say(f"step: {step.name}")
        started = time.perf_counter()
        code = _run(step.command, log)
        _say(f"step: {step.name} -> exit {code} after {(time.perf_counter() - started) / 60:.1f} min")
        if code != 0:
            failures.append(step.name)
    for name in skipped:
        sys.stdout.write(f"  SKIPPED (missing input): {name}\n")
    for name in failures:
        sys.stdout.write(f"  FAILED: {name}\n")
    sys.stdout.write("RESULT: " + ("FAIL" if failures else "PASS") + f" (log: {log})\n")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    tests = commands.add_parser("unit-tests", help="run the lattice-ZK and touched-module tests")
    tests.add_argument("--junit-xml", help="also write a JUnit XML report of the pytest part")
    tests.set_defaults(handler=unit_tests)

    data = commands.add_parser("prepare-data", help="verify/download sources, encode and verify covers")
    data.add_argument("--raw", default="data/raw")
    data.add_argument("--encoded", default="data/encoded")
    data.add_argument("--download", action="store_true", help="download missing Y4M files from Xiph")
    data.add_argument("--only", nargs="*", help="encode names from scripts/data_manifest.json")
    data.add_argument("--no-encode", action="store_true", help="only check the Y4M sources")
    data.add_argument("--strict-encoded", action="store_true",
                      help="fail (instead of warn) when an encoded cover differs from the reference hash")
    data.set_defaults(handler=prepare_data)

    short = commands.add_parser("small", help="one registered E2E run on a short cut (about 10-15 min)")
    short.add_argument("--video", default=DEFAULT_SMALL_VIDEO)
    short.add_argument("--frames", type=int, default=100)
    short.add_argument("--carrier", choices=sorted(SMALL_CHUNK_BYTES), default="t1")
    short.add_argument("--chunk-bytes", type=int, help="default: 8000 for t1, 3800 for magnitude")
    short.add_argument("--work", default="tmp/repro_small")
    short.add_argument("--security-checks", action="store_true",
                       help="also replay the session and verify a tampered copy (two more verifications)")
    short.add_argument("--keep", action="store_true", help="keep the stego video after a passing run")
    short.set_defaults(handler=small)

    full = commands.add_parser("all", help="the whole evaluation; tens of hours")
    full.add_argument("--workers", type=int, default=2, help="parallel sweep cases (1-3 GB RAM each)")
    full.add_argument("--download", action="store_true")
    full.add_argument("--skip-prepare", action="store_true")
    full.add_argument("--fresh", action="store_true",
                      help="move benchmark/results/q2 and tmp/q2 aside first so every step reruns")
    full.set_defaults(handler=reproduce_all)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONUTF8", "1")
    arguments = _parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
