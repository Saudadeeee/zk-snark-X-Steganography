"""LaTeX table bodies for doc/paper generated from the recorded results (no hand-copied numbers).

    py -3.12 -m benchmark.paper_tables_new

Writes doc/paper/tables/{steganalysis,quality,channel}.tex, \\input by the evaluation section.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results" / "stego_compare"
TABLES = ROOT / "doc" / "paper" / "tables"
METHODS = (("low-drift", r"Ours, low-drift"), ("random", r"Ours, random"),
           ("wang2018", r"Wang \& Ma~\cite{wang2018cavlc}"), ("lin2012", r"Lin et al.~\cite{lin2012cavlc}"),
           ("liao2009", r"Liao-style~\cite{liao2012t1journal}"), ("kim2007", r"Kim et al.~\cite{kim2007t1}"))
END = " \\\\\n"


def steganalysis() -> str:
    data = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))["steganalysis"]
    lines = []
    for method, label in METHODS:
        cells = [f"{data[d][method][r]['frame_p_e']:.2f}" for d in ("cavlc", "spam", "srmlite", "cnn")
                 for r in ("cap64", "rate5", "rate20")]
        lines.append(label + " & " + " & ".join(cells) + END)
    return "".join(lines)


def _rows(dataset: str) -> list[dict]:
    """Rows of a comparison run, de-duplicated on (source, qp, gop, method, rate) (last one wins)."""
    path = RESULTS / f"{dataset}.jsonl"
    if not path.is_file():
        return []
    unique: dict[tuple, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        unique[(row["source"], row["qp"], row["gop"], row["method"], row["rate"])] = row
    return list(unique.values())


def quality() -> str:
    """Median over sequences of mean-MSE PSNR-Y for QP 22 and 34, GOP 1 and 30, at 64 bits per IDR."""
    rows = {"cif": _rows("cif"), "hd": _rows("hd")}
    lines = []
    for method, label in METHODS:
        cells = []
        for dataset in ("cif", "hd"):
            for gop in (1, 30):
                for qp in (22, 34):
                    values = [r["psnr_y_mean_mse"] for r in rows[dataset] if r["method"] == method
                              and r["gop"] == gop and r["qp"] == qp and r["rate"] == "cap64"
                              and math.isfinite(r["psnr_y_mean_mse"])]
                    cells.append(f"{statistics.median(values):.1f}" if values else "--")
        lines.append(label + " & " + " & ".join(cells) + END)
    return "".join(lines)


def channel() -> str:
    lines = []
    for dataset, label in (("cif", "CIF"), ("hd", "HD")):
        path = RESULTS / f"channel_options_{dataset}.jsonl"
        if not path.is_file():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for select in ("random", "low-drift"):
            for key_mode in ("master", "per-video"):
                part = [r for r in rows if r["select"] == select and r["key_mode"] == key_mode]
                ok = sum(r["extract_ok"] for r in part)
                token = f"{sum(r['token_extract_ok'] for r in part)}/{len(part)}" if key_mode == "per-video" else "--"
                psnr = [r["psnr_y_carrying_mean_mse"] for r in part if r["psnr_y_carrying_mean_mse"]]
                worst = [r["psnr_y_carrying_min"] for r in part if r["psnr_y_carrying_min"]]
                lines.append(f"{label} & \\texttt{{{select}}} & \\texttt{{{key_mode}}} & {len(part)} & {ok}/{len(part)} & "
                             f"{token} & {statistics.median(psnr):.1f} & {min(worst):.1f} & "
                             f"{statistics.median(r['embed_s'] for r in part):.1f}" + END)
        lines.append("\\midrule\n")
    return "".join(lines[:-1])


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    for name, build in (("steganalysis", steganalysis), ("quality", quality), ("channel", channel)):
        (TABLES / f"{name}.tex").write_text(build(), encoding="utf-8")
    print("tables written to doc/paper/tables")


if __name__ == "__main__":
    main()
