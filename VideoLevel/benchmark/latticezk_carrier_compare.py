"""Side-by-side comparison of the magnitude-LSB and trailing-one-sign carriers.

Pairs every ``<case>`` with ``<case>_t1`` from ``benchmark/results/q2`` and
reports capacity, frames used, decoded quality, timing, classical
steganalysis and learned steganalysis (leave-one-clip-out over the paired
clips, same detector and features for both carriers).

    python -m benchmark.latticezk_carrier_compare --output benchmark/results/q2/carrier_compare.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "q2"
FEATURES = ROOT / "tmp" / "q2"
CARRIERS = (("magnitude", ""), ("t1", "_t1"), ("t1-spread", "_t1_spread"))
RENAMED = {  # variant case names that differ from "<magnitude case><suffix>"
    ("hall_cif_q22_reg", "_t1"): "hall_monitor_cif_q22_reg_t1",
}


def _variant_name(case: str, suffix: str) -> str:
    return case if not suffix else RENAMED.get((case, suffix), f"{case}{suffix}")


def _t1_name(case: str) -> str:
    return _variant_name(case, "_t1")


def _load(name: str, prefix: str) -> dict[str, Any] | None:
    path = RESULTS / f"{prefix}_{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def paired_cases() -> list[str]:
    cases = []
    for path in sorted(RESULTS.glob("e2e_*_reg.json")):
        case = path.stem.removeprefix("e2e_")
        if (RESULTS / f"e2e_{_t1_name(case)}.json").exists():
            cases.append(case)
    return cases


def _capacity_for(video: str, carrier: str) -> list[dict[str, Any]] | None:
    """Full-clip capacity scan of ``video`` for ``carrier``, preferring the most segments."""
    best = None
    for path in RESULTS.glob("capacity_*.json"):
        scans = json.loads(path.read_text(encoding="utf-8"))
        scan = scans[0]
        if scan["video"] == video and scan.get("carrier", "magnitude") == carrier:
            if best is None or scan["segments_scanned"] > best[0]["segments_scanned"]:
                best = scans
    return best


def _row(case: str, carrier: str) -> dict[str, Any] | None:
    name = _variant_name(case, dict(CARRIERS)[carrier])
    if not (RESULTS / f"e2e_{name}.json").exists():
        return None
    e2e, classical = _load(name, "e2e"), _load(name, "steg")
    capacity = _capacity_for(e2e["input_video"], "t1" if carrier.startswith("t1") else carrier)
    quality = e2e.get("frame_quality") or {}
    row = {
        "case": case, "carrier": carrier, "verified": e2e["blind_video_only_verification"],
        "segments": e2e["segments_used"], "frames_modified": quality.get("frames_modified"),
        "psnr_mod": quality.get("luma_psnr_modified_frames_db"),
        "psnr_worst": quality.get("luma_psnr_worst_frame_db"),
        "ssim": e2e["decoded_quality"]["ssim_all"],
        "embed_s": e2e["timings_s"]["embed_s"], "verify_s": e2e["timings_s"]["verify_s"],
        "capacity_kbit_per_100f": None,
    }
    if capacity:
        bits = capacity[0]["carrier_bits_per_segment"]
        row["capacity_kbit_per_100f"] = round(min(bits) / 1000, 1)
    if classical:
        row["t1_sign_p"] = classical["trailing_one_signs"]["p_value"]
        row["position_sign_p"] = classical["per_scan_position_signs"]["p_value"]
        row["pov_stego"] = classical["pairs_of_values_attack"]["stego"]["embedding_probability"]
        row["magnitude_hist_p"] = classical["magnitude_histogram"]["p_value"]
    return row


def learned(cases: list[str]) -> dict[str, Any]:
    results = {}
    for carrier, suffix in CARRIERS:
        paths = [FEATURES / f"mlfeat_{_variant_name(case, suffix)}.npz" for case in cases]
        if len(paths) < 2 or not all(path.exists() for path in paths):
            continue
        report = steg.evaluate(paths)
        best = report["protocols"]["leave_one_clip_out"]
        results[carrier] = {
            "frame_pairs": report["frame_pairs"],
            "coefficient_fld": best["coefficient/fld_ensemble"]["p_e_mean"],
            "combined_fld": best["combined/fld_ensemble"]["p_e_mean"],
            "pixel_fld": best["pixel/fld_ensemble"]["p_e_mean"],
            "paired_combined_fld": report["protocols"]["paired_half_split"]["combined/fld_ensemble"]["p_e_mean"],
        }
    return results


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build() -> str:
    cases = paired_cases()
    rows = [row for case in cases for carrier, _ in CARRIERS if (row := _row(case, carrier))]
    lines = ["# Carrier comparison: magnitude-LSB vs trailing-one sign (generated)\n",
             f"Paired clips: {', '.join(cases) or 'none yet'}\n",
             "| Case | Carrier | Verified | Capacity (kbit/100 fr.) | Segments | Frames mod. | PSNR mod. | "
             "Worst | SSIM | Embed (s) | Verify (s) | T1-sign p | Pos.-sign p | PoV stego | Mag. hist p |",
             "|" + "---|" * 15]
    for row in rows:
        lines.append("| " + " | ".join([
            row["case"], row["carrier"], _fmt(row["verified"]), _fmt(row["capacity_kbit_per_100f"], 1),
            _fmt(row["segments"]), _fmt(row["frames_modified"]), _fmt(row["psnr_mod"]),
            _fmt(row["psnr_worst"]), _fmt(row["ssim"], 5), _fmt(row["embed_s"], 0), _fmt(row["verify_s"], 0),
            _fmt(row.get("t1_sign_p"), 3), _fmt(row.get("position_sign_p"), 3),
            _fmt(row.get("pov_stego"), 3), _fmt(row.get("magnitude_hist_p"), 3),
        ]) + " |")
    ml = learned(cases)
    if ml:
        lines += ["", "## Learned steganalysis (P_E; 0.5 = chance)", "",
                  "| Carrier | Frame pairs | Coefficient LOCO | Combined LOCO | Pixel LOCO | Combined paired |",
                  "|---|---|---|---|---|---|"]
        for carrier, result in ml.items():
            lines.append(f"| {carrier} | {result['frame_pairs']} | {result['coefficient_fld']:.3f} | "
                         f"{result['combined_fld']:.3f} | {result['pixel_fld']:.3f} | "
                         f"{result['paired_combined_fld']:.3f} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    text = build()
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
