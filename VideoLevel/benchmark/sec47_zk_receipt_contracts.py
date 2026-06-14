"""Section 47 - ZK receipt circuit contract diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.trust import build_zk_receipt_contract_report


ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "benchmark" / "results"
DIAGNOSTIC_PATH = RESULTS_DIR / "trust_architecture_diagnostic.json"
OUTPUT_PATH = RESULTS_DIR / "sec47_zk_receipt_contracts_data.json"


def _load_or_run_diagnostic() -> dict[str, Any]:
    if DIAGNOSTIC_PATH.exists():
        data = json.loads(DIAGNOSTIC_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("circuits"):
            return data
    from benchmark.trust_architecture_diagnostic import run_diagnostic

    return run_diagnostic()


def run() -> dict[str, Any]:
    print("\n=== Section 47 ZK Receipt Circuit Contracts ===")
    diagnostic = _load_or_run_diagnostic()
    report = build_zk_receipt_contract_report(diagnostic.get("circuits", {}))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"  all_contracts_valid: {summary['all_contracts_valid']}")
    print(f"  valid_contract_count: {summary['valid_contract_count']}/{summary['circuit_count']}")
    print(f"  groth16_bound_count: {summary['groth16_bound_count']}/{summary['circuit_count']}")
    for name, circuit in report["circuits"].items():
        print(f"  {name}: contract_valid={circuit['contract_valid']}")
    return report


if __name__ == "__main__":
    run()
