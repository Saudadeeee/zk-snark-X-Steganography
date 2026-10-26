"""Capacity-planning dry run: fixed (ZKBC v1) versus adaptive (ZKBC v2) chunking.

Replays the measured per-segment capacities of the capacity scans
(``benchmark/results/q2/capacity_*.json``) for the sweep cases that were
skipped with "envelope does not fit the scanned capacity", and reports whether
the registered envelope fits under

* the sweep's fixed-chunk rule (``latticezk_q2_sweep._auto_chunk``),
* the best possible fixed chunk size (exhaustive search), and
* the adaptive plan (``src.transport.adaptive_chunks.plan_layout``) at the case density,

with the segments the adaptive plan uses.  No video is touched.

    python -m benchmark.latticezk_adaptive_chunk_plan \
        --output benchmark/results/q2/adaptive_chunk_plan_4cif.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.transport.adaptive_chunks import FRAMING_BYTES, AdaptiveChunkPlan, plan_layout  # noqa: E402
from src.transport.blind_payload_chunks import CHUNK_HEADER as V1_CHUNK_HEADER  # noqa: E402
from src.transport.blind_payload_chunks import MAX_CHUNK_BYTES as V1_MAX_CHUNK_BYTES  # noqa: E402
from src.lattice_zk import video_proof  # noqa: E402
from src.lattice_zk.params import BDLOP_OPEN_128_V1, BDLOP_OPEN_128_V2, BDLOP_OPEN_128_V3  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "q2"
V1_FRAMING_BYTES = 14 + V1_CHUNK_HEADER.size  # ZKVP envelope header + ZKBC v1 header
SWEEP_CHUNK_MARGIN = 0.97  # latticezk_q2_sweep.CHUNK_MARGIN
# Skipped sweep cases (and reference cases), each with its most complete scan.
CASES = (
    ("crew4cif_q22_reg", "capacity_crew4cif_q22_reg_s6.json", 1.0),
    ("soccer4cif_q22_reg", "capacity_soccer4cif_q22_reg.json", 1.0),
    ("crew4cif_q22_reg_d50", "capacity_crew4cif_q22_reg_s6.json", 0.5),
    ("crew4cif_q22_reg_d25", "capacity_crew4cif_q22_reg_s6.json", 0.25),
    ("soccer4cif_q22_reg_d50", "capacity_soccer4cif_q22_reg.json", 0.5),
    ("soccer4cif_q22_reg_d25", "capacity_soccer4cif_q22_reg.json", 0.25),
    ("crew4cif_q18_reg", "capacity_crew4cif_q18_reg.json", 1.0),
    ("city4cif_q22_reg", "capacity_city4cif_q22_reg.json", 1.0),
    ("harbour4cif_q22_reg", "capacity_harbour4cif_q22_reg.json", 1.0),
)


def sweep_uniform_rule(envelope: int, scan: dict[str, Any], density: float) -> dict[str, Any]:
    """The sweep's fixed-chunk choice: 97 % of the smallest scanned segment."""
    chunk = min(int(scan["min_chunk_bytes_supported"] * SWEEP_CHUNK_MARGIN * density),
                V1_MAX_CHUNK_BYTES)
    needed = math.ceil(envelope / chunk) if chunk > 0 else None
    available = scan["segments_scanned"] if density == 1.0 else scan["segments_total"]
    return {"chunk_bytes": chunk, "segments_needed": needed,
            "fits": needed is not None and needed <= available}


def best_uniform_chunk(envelope: int, capacities: list[int], fill_permille: int) -> int | None:
    """Largest fixed chunk size whose v1 chunks fit segments 0, 1, ... in order."""
    usable = [bits * fill_permille // 1000 // 8 - V1_FRAMING_BYTES for bits in capacities]
    for chunk in range(min(V1_MAX_CHUNK_BYTES, envelope), 0, -1):
        count = math.ceil(envelope / chunk)
        if count > len(usable):
            return None  # smaller chunks only need more segments
        sizes = [chunk] * (count - 1) + [envelope - chunk * (count - 1)]
        if all(size <= room for size, room in zip(sizes, usable)):
            return chunk
    return None


def adaptive(envelope: int, scan: dict[str, Any], plan: AdaptiveChunkPlan) -> dict[str, Any]:
    capacities = scan["carrier_bits_per_segment"]
    unscanned = scan["segments_total"] - len(capacities)
    try:
        layout = plan_layout(envelope, capacities, plan)
    except ValueError:
        room = sum(plan.chunk_capacity_bytes(bits) for bits in capacities)
        return {
            "fits": False if unscanned == 0 else None,
            "verdict": ("does not fit the whole video" if unscanned == 0 else
                        f"undetermined: {envelope - room} B more needed from "
                        f"{unscanned} unscanned segment(s)"),
            "usable_bytes_scanned": room,
            "shortfall_bytes": envelope - room,
        }
    used = [slot.segment_index for slot in layout]
    return {
        "fits": True,
        "verdict": f"fits in {len(used)} segment(s)",
        "segments_used": used,
        "segments_skipped": [index for index in range(used[-1] + 1) if index not in used],
        "chunk_bytes": [slot.size for slot in layout],
        "frames_spanned": (used[-1] + 1) * 100,
    }


def plan_case(name: str, scan_file: str, density: float, results: Path,
              min_chunk_bytes: int) -> dict[str, Any]:
    scan = json.loads((results / scan_file).read_text(encoding="utf-8"))[0]
    fill = round(density * 1000)
    plan = AdaptiveChunkPlan(min_chunk_bytes=min_chunk_bytes, fill_permille=fill)
    report: dict[str, Any] = {
        "case": name, "scan": scan_file, "video": scan["video"], "density": density,
        "frames": scan["frames"], "segments_total": scan["segments_total"],
        "segments_scanned": scan["segments_scanned"],
        "carrier_bits_per_segment": scan["carrier_bits_per_segment"],
        "chunk_plan": plan.descriptor(), "envelopes": {},
    }
    for params in (BDLOP_OPEN_128_V3, BDLOP_OPEN_128_V2, BDLOP_OPEN_128_V1):
        envelope = video_proof.envelope_size(params, registered=True)
        best = best_uniform_chunk(envelope, scan["carrier_bits_per_segment"], fill)
        report["envelopes"][params.name] = {
            "registered_envelope_bytes": envelope,
            "sweep_uniform_rule": sweep_uniform_rule(envelope, scan, density),
            "best_uniform_chunk_bytes": best,
            "best_uniform_fits_scanned": best is not None,
            "adaptive": adaptive(envelope, scan, plan),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--min-chunk-bytes", type=int, default=AdaptiveChunkPlan().min_chunk_bytes)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    reports = [plan_case(name, scan, density, arguments.results, arguments.min_chunk_bytes)
               for name, scan, density in CASES]
    document = {
        "description": "dry run of the adaptive ZKBC v2 plan on measured carrier capacities",
        "framing_bytes": {"v1_fixed": V1_FRAMING_BYTES, "v2_adaptive": FRAMING_BYTES},
        "cases": reports,
    }
    text = json.dumps(document, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    for case in reports:
        production = case["envelopes"][BDLOP_OPEN_128_V3.name]
        legacy = case["envelopes"][BDLOP_OPEN_128_V1.name]
        sys.stdout.write(
            f"{case['case']:24s} sweep-uniform={production['sweep_uniform_rule']['fits']!s:5s} "
            f"best-uniform={production['best_uniform_fits_scanned']!s:5s} "
            f"adaptive={production['adaptive']['verdict']}"
            f" | v1 adaptive={legacy['adaptive']['verdict']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
