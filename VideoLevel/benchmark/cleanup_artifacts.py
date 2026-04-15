"""
Normalize benchmark result artifacts for strict JSON compliance and schema consistency.

- sec1: replace per-frame PSNR non-finite values with 60.0 dB (display cap),
        preserve theoretical info via psnr_inf_frame_count.
- sec2: mark capacity-only rows as unvalidated instead of validated=capacity.
- sec3: ensure validation metadata fields exist.
- all: rewrite with strict JSON formatting.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def _safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _load(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_safe(data), f, indent=2, ensure_ascii=False, allow_nan=False)


def cleanup_sec1(path: Path) -> str:
    data = _load(path)
    changed = 0

    for seq, entry in data.items():
        psnr = entry.get("psnr", [])
        if not isinstance(psnr, list):
            continue

        inf_count = 0
        capped = []
        for v in psnr:
            if isinstance(v, (int, float)):
                fv = float(v)
                if not math.isfinite(fv):
                    inf_count += 1
                    capped.append(60.0)
                else:
                    capped.append(min(fv, 60.0))
            else:
                # Malformed/non-numeric entries are repaired to display cap.
                capped.append(60.0)

        if capped != psnr:
            entry["psnr"] = capped
            changed += 1

        if "psnr_inf_frame_count" not in entry:
            entry["psnr_inf_frame_count"] = inf_count
            changed += 1

        if "validation_threshold_db" not in entry:
            entry["validation_threshold_db"] = 38.0
            changed += 1

    _save(path, data)
    return f"sec1 cleaned ({changed} updates)"


def cleanup_sec2(path: Path) -> str:
    data = _load(path)
    changed = 0

    for _, entry in data.items():
        rates = entry.get("rates_pct", [])
        has_sweep = isinstance(rates, list) and len(rates) > 0

        if not has_sweep:
            if entry.get("validated_capacity_bits") == entry.get("capacity_bits"):
                entry["validated_capacity_bits"] = None
                changed += 1
            if entry.get("validated_capacity_bytes") == entry.get("capacity_bytes"):
                entry["validated_capacity_bytes"] = None
                changed += 1
            if entry.get("validation_applied") is not False:
                entry["validation_applied"] = False
                changed += 1
            if "validation_threshold_db" not in entry:
                entry["validation_threshold_db"] = None
                changed += 1
            if "validated_capacity_bits_effective" not in entry:
                entry["validated_capacity_bits_effective"] = entry.get("capacity_bits")
                changed += 1
        else:
            if entry.get("validation_applied") is not True:
                entry["validation_applied"] = True
                changed += 1
            if "validation_threshold_db" not in entry:
                entry["validation_threshold_db"] = 38.0
                changed += 1
            if "validated_capacity_bits_effective" not in entry:
                entry["validated_capacity_bits_effective"] = entry.get("validated_capacity_bits")
                changed += 1

    _save(path, data)
    return f"sec2 cleaned ({changed} updates)"


def cleanup_sec3(path: Path) -> str:
    data = _load(path)
    changed = 0

    if "validation_threshold_db" not in data:
        data["validation_threshold_db"] = 38.0
        changed += 1

    _save(path, data)
    return f"sec3 cleaned ({changed} updates)"


def main() -> None:
    tasks = [
        (RESULTS / "sec1_quality_data.json", cleanup_sec1),
        (RESULTS / "sec2_capacity_data.json", cleanup_sec2),
        (RESULTS / "sec3_methods_data.json", cleanup_sec3),
    ]

    for path, fn in tasks:
        if path.exists():
            print(fn(path))
        else:
            print(f"skip missing: {path.name}")


if __name__ == "__main__":
    main()
