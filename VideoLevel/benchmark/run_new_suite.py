"""Run every measured benchmark and write the single consolidated report.

Output: benchmark/results/benchmark_report_new.pdf (one file with every section),
backed by the raw records it is built from (*_new.json, media_new/<run-id>/).
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.crypto_benchmark_new import run_crypto_benchmark
from benchmark.e2e_benchmark_new import run_e2e_benchmark
from benchmark.media_benchmark_new import convert_sources_full, run_media_benchmark
from benchmark.reports_new import build_report
from benchmark.zkp_benchmark_new import run_zkp_benchmark


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"


def main() -> int:
    conversion = convert_sources_full(RESULTS)
    print("CONVERSION", json.dumps({"converted": conversion["converted"], "failed": conversion["failed"]}, sort_keys=True), flush=True)
    media = run_media_benchmark(RESULTS, max_frames=30)
    print("MEDIA", json.dumps(media["summary"], sort_keys=True), flush=True)
    e2e = run_e2e_benchmark(RESULTS, trials=5)
    print("E2E", json.dumps(e2e["summary"], sort_keys=True), flush=True)
    crypto = run_crypto_benchmark(RESULTS / "security_new.json")
    print("SECURITY", len(crypto["results"]), "measured rows", flush=True)
    # PLONK proving takes minutes per proof on this circuit; one trial keeps the suite bounded.
    zkp = run_zkp_benchmark(RESULTS, trials=5, plonk_trials=1)
    zkp_ok = all(row["proof_valid"] and row["tampered_public_input_rejected"] for row in zkp["results"])
    print("ZKP", len(zkp["results"]), "proof runs, all valid" if zkp_ok else "proof runs, FAILURES", flush=True)
    print("REPORT", build_report(RESULTS).relative_to(ROOT).as_posix(), flush=True)
    passed = conversion["failed"] == 0 and media["summary"]["all_passed"] and e2e["summary"]["all_passed"] and zkp_ok
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
