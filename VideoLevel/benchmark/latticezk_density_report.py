"""Detectability and quality versus embedding density on the 4CIF clips.

Groups the registered 4CIF runs by density (``_reg`` = 100 %, ``_reg_d50``,
``_reg_d25`` ...), evaluates learned steganalysis leave-one-clip-out within
each density level, and writes a table plus ``docs/paper/figures/density.pdf``.

    python -m benchmark.latticezk_density_report --output benchmark/results/q2/density_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_ml_steganalysis as steg  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "q2"
FEATURES = ROOT / "tmp" / "q2"
PAPER = ROOT / "docs" / "paper"
CASE = re.compile(r"^(?P<clip>[a-z]+)4cif_q22_reg(?:_d(?P<density>\d+))?$")


def collect() -> dict[float, list[str]]:
    groups: dict[float, list[str]] = {}
    for path in sorted(RESULTS.glob("e2e_*4cif_q22_reg*.json")):
        match = CASE.match(path.stem.removeprefix("e2e_"))
        if match is None:
            continue
        density = int(match["density"]) / 100 if match["density"] else 1.0
        groups.setdefault(density, []).append(path.stem.removeprefix("e2e_"))
    return groups


def summarise(groups: dict[float, list[str]]) -> dict[str, Any]:
    levels = {}
    for density, cases in sorted(groups.items(), reverse=True):
        reports = [json.loads((RESULTS / f"e2e_{case}.json").read_text(encoding="utf-8")) for case in cases]
        quality = [report.get("frame_quality") or {} for report in reports]
        level: dict[str, Any] = {
            "cases": cases,
            "all_verified": all(report["blind_video_only_verification"] for report in reports),
            "mean_frames_modified": sum(q.get("frames_modified", 0) for q in quality) / len(quality),
            "mean_psnr_modified": _mean([q.get("luma_psnr_modified_frames_db") for q in quality]),
            "min_psnr_worst": min((q.get("luma_psnr_worst_frame_db") for q in quality
                                   if q.get("luma_psnr_worst_frame_db") is not None), default=None),
        }
        features = [FEATURES / f"mlfeat_{case}.npz" for case in cases]
        present = [path for path in features if path.exists()]
        if len(present) >= 2:
            report = steg.evaluate(present)
            loco = report["protocols"]["leave_one_clip_out"]
            level["learned"] = {
                "frame_pairs": report["frame_pairs"],
                "coefficient_fld": loco["coefficient/fld_ensemble"]["p_e_mean"],
                "pixel_fld": loco["pixel/fld_ensemble"]["p_e_mean"],
                "combined_fld": loco["combined/fld_ensemble"]["p_e_mean"],
            }
        levels[f"{density:g}"] = level
    return levels


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 3) if present else None


def figure(levels: dict[str, Any]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = [(float(density), level["learned"]) for density, level in levels.items() if "learned" in level]
    if len(points) < 2:
        return
    points.sort()
    (PAPER / "figures").mkdir(parents=True, exist_ok=True)
    figure_, axis = plt.subplots(figsize=(4.5, 3))
    for key, label in (("coefficient_fld", "coefficient features"), ("pixel_fld", "pixel features"),
                       ("combined_fld", "combined")):
        axis.plot([100 * d for d, _ in points], [learned[key] for _, learned in points], marker="o", label=label)
    axis.axhline(0.5, linestyle="--", color="grey", linewidth=0.8)
    axis.set_xlabel("Embedding density (% of carriers used per segment)")
    axis.set_ylabel("Detection error $P_E$ (LOCO)")
    axis.legend(fontsize=7)
    figure_.tight_layout()
    figure_.savefig(PAPER / "figures" / "density.pdf")
    plt.close(figure_)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    levels = summarise(collect())
    figure(levels)
    text = json.dumps(levels, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
