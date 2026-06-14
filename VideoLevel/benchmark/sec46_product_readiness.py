"""Section 46 - Upgrade-v2 Product Readiness Gate."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.trust.product_readiness import evaluate_product_readiness, write_product_readiness_report


def run() -> dict[str, Any]:
    print("\n=== Section 46 Product Readiness Gate ===")
    report = evaluate_product_readiness()
    write_product_readiness_report(report)

    summary = report["summary"]
    print(f"  seed_surface_ready: {summary['seed_surface_ready']}")
    print(f"  all_product_ready: {summary['all_product_ready']}")
    print(f"  product_ready_count: {summary['product_ready_count']}/{summary['total_feature_count']}")

    for feature in report["features"]:
        name = feature["feature"]
        status = feature["status"]
        blocker_count = len(feature["product_blockers"])
        print(f"  {name}: {status}, blockers={blocker_count}")
    return report


if __name__ == "__main__":
    run()
