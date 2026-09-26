"""Run all measured current benchmarks and build clearly named *_new reports."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.crypto_benchmark_new import run_crypto_benchmark
from benchmark.media_benchmark_new import convert_sources_full, run_media_benchmark
from benchmark.reports_new import build_reports
from benchmark.zkp_benchmark_new import run_zkp_benchmark


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"


def main() -> int:
    conversion = convert_sources_full(RESULTS)
    print("CONVERSION", json.dumps({"converted": conversion["converted"], "failed": conversion["failed"]}, sort_keys=True), flush=True)
    media = run_media_benchmark(RESULTS, max_frames=30)
    print("MEDIA", json.dumps(media["summary"], sort_keys=True), flush=True)
    crypto = run_crypto_benchmark(RESULTS / "security_new.json")
    print("SECURITY", len(crypto["results"]), "measured rows", flush=True)
    zkp = run_zkp_benchmark(RESULTS, trials=3)
    print("ZKP", len(zkp["results"]), "proof runs", flush=True)
    for report in build_reports(RESULTS):
        print("REPORT", report, flush=True)
    return 0 if media["summary"]["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
