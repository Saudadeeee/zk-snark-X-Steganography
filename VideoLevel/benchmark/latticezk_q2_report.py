"""Aggregate the lattice-ZK evaluation into paper tables and figures.

Reads ``benchmark/results/q2/`` (E2E, steganalysis, learned steganalysis,
capacity, baselines) and writes:

* ``benchmark/results/q2/SUMMARY.md``   -- human-readable tables;
* ``docs/paper/tables/*.tex``           -- LaTeX tables for the manuscript;
* ``docs/paper/figures/*.pdf``          -- capacity and quality figures.

    python -m benchmark.latticezk_q2_report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results" / "q2"
PAPER = ROOT / "docs" / "paper"


def _load(pattern: str) -> dict[str, Any]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(RESULTS.glob(pattern))}


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def e2e_rows() -> list[dict[str, Any]]:
    rows = []
    for stem, report in _load("e2e_*.json").items():
        if stem.endswith(".skipped") or "input_video" not in report:
            continue  # cases the sweep skipped for capacity have no run to report
        quality = report.get("frame_quality") or {}
        rows.append({
            "case": stem.removeprefix("e2e_"),
            "video": report["input_video"],
            "mode": "registered" if report["mode"].startswith("registered") else "in-band",
            "envelope_bytes": report["envelope_bytes"],
            "carriers": report["carriers_used"],
            "segments": report["segments_used"],
            "verified": report["blind_video_only_verification"],
            "replay_rejected": report.get("replay_rejected"),
            "tamper_rejected": report.get("tamper_rejected"),
            "psnr_mod": quality.get("luma_psnr_modified_frames_db"),
            "psnr_worst": quality.get("luma_psnr_worst_frame_db"),
            "frames_mod": quality.get("frames_modified"),
            "frames": quality.get("frames"),
            "ssim": (report.get("decoded_quality") or {}).get("ssim_all"),
            "embed_s": report["timings_s"].get("embed_s"),
            "verify_s": report["timings_s"].get("verify_s"),
        })
    return rows


def _envelope_bits(registered: bool) -> int:
    from src.lattice_zk import video_proof
    from src.lattice_zk.params import BDLOP_OPEN_128

    return video_proof.envelope_size(BDLOP_OPEN_128, registered=registered) * 8


def capacity_rows() -> list[dict[str, Any]]:
    rows = []
    for stem, reports in _load("capacity_*.json").items():
        for report in reports:
            bits = report["carrier_bits_per_segment"]
            rows.append({
                "video": report["video"], "frames": report["frames"],
                "bits_per_100_frames_min": min(bits), "bits_per_100_frames_mean": sum(bits) / len(bits),
                "total_bits": sum(bits),
                "registered_fits": sum(bits) >= _envelope_bits(True) * 1.05,
                "in_band_fits": sum(bits) >= _envelope_bits(False) * 1.05,
            })
    return rows


def _span(values: list[float]) -> str:
    low, high = min(values), max(values)
    return f"{low:.3f}" if abs(high - low) < 5e-4 else f"{low:.3f}-{high:.3f}"


def cnn_rows() -> list[dict[str, Any]]:
    """Group CNN runs by (carrier, protocol, change) and report seed ranges."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for report in _load("cnn_*.json").values():
        amplify = float(report["config"].get("amplify") or 1.0)
        change = "real" if amplify == 1.0 else f"{amplify:g}x amplified"
        key = (report["case_set"].replace("_", "-"), report["protocol"], change)
        groups.setdefault(key, []).append(report)
    rows = []
    for (carrier, protocol, change), reports in sorted(groups.items(), key=lambda item: (item[0][0], item[0][2] != "real", item[0][1])):
        summaries = [report["summary"] for report in reports]
        rows.append({
            "carrier": carrier,
            "protocol": "leave-one-clip-out" if protocol == "loco" else "paired split",
            "change": change,
            "pairs": reports[0]["frame_pairs"],
            "seeds": len(reports),
            "p_e": _span([s["frame_p_e_mean"] for s in summaries]),
            "auc": _span([s["frame_auc_mean"] for s in summaries]),
            "p_e_full": _span([s["frame_full_logit_p_e_mean"] for s in summaries]),
            "p_e_segment": _span([s["video_segment_pooled"]["p_e"] for s in summaries]),
        })
    return rows


ADAPTIVE_MODE_NAMES = {"magnitude": "direct", "adaptive": "STC uniform", "adaptive-texture": "STC texture"}


def adaptive_rows() -> dict[str, Any] | None:
    """Rows of the B1 comparison (``adaptive_e2e.json``), direct mode first."""
    path = RESULTS / "adaptive_e2e.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    tags = sorted(report["modes"], key=lambda tag: list(ADAPTIVE_MODE_NAMES).index(report["modes"][tag]))
    names = [ADAPTIVE_MODE_NAMES[report["modes"][tag]] for tag in tags]
    runs = []
    for case, run in sorted(report["cases"].items()):
        tag = case.rsplit("_", 1)[-1]
        quality, timings = run["frame_quality"], run["timings_s"]
        runs.append({
            "clip": case.split("_")[0], "order": tags.index(tag), "mode": ADAPTIVE_MODE_NAMES[run["carrier"]],
            "carriers": run["carriers_used"], "changes": run["changes"]["coefficients"],
            "per_bit": run["changes_per_envelope_bit"], "psnr_mod": quality["luma_psnr_modified_frames_db"],
            "psnr_worst": quality["luma_psnr_worst_frame_db"],
            "embed_s": timings["embed_s"], "verify_s": timings["verify_s"],
        })
    runs.sort(key=lambda row: (row["clip"], row["order"]))
    protocols = {"leave_one_clip_out": "leave-one-clip-out", "paired_half_split": "paired split"}
    detection: dict[tuple[str, str], list[float]] = {}
    if not report.get("detection"):  # learned steganalysis deferred for this run
        return {"runs": runs, "modes": names, "detection": {}, "frame_pairs": 0}
    for key, label in protocols.items():
        for name in report["detection"][tags[0]]["protocols"][key]:
            detection[(label, name)] = [report["detection"][tag]["protocols"][key][name]["p_e_mean"]
                                        for tag in tags]
    for label in protocols.values():
        rows = [values for (protocol, _), values in detection.items() if protocol == label]
        detection[(label, "worst case")] = [min(column) for column in zip(*rows)]
    return {"runs": runs, "modes": names, "detection": detection,
            "frame_pairs": report["detection"][tags[0]]["frame_pairs"]}


def _markdown(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _latex(headers: list[str], rows: list[list[str]], caption: str, label: str) -> str:
    def escape(text: str) -> str:
        return text.replace("_", r"\_").replace("%", r"\%")

    body = "\n".join(" & ".join(escape(cell) for cell in row) + r" \\" for row in rows)
    return (
        "\\begin{table}[t]\n\\centering\n\\caption{" + caption + "}\n\\label{" + label + "}\n"
        "\\resizebox{\\linewidth}{!}{%\n\\begin{tabular}{" + "l" * len(headers) + "}\n\\toprule\n"
        + " & ".join(escape(h) for h in headers) + r" \\" + "\n\\midrule\n" + body
        + "\n\\bottomrule\n\\end{tabular}}\n\\end{table}\n"
    )


def build() -> str:
    sections: list[str] = ["# Lattice-ZK evaluation summary (generated)\n"]
    tables: dict[str, str] = {}

    e2e = e2e_rows()
    if e2e:
        headers = ["Case", "Mode", "Envelope (B)", "Carriers", "Verified", "Replay rej.", "Tamper rej.",
                   "PSNR mod. (dB)", "Worst (dB)", "Frames mod.", "SSIM", "Embed (s)", "Verify (s)"]
        rows = [[r["case"], r["mode"], _fmt(r["envelope_bytes"]), _fmt(r["carriers"]), _fmt(r["verified"]),
                 _fmt(r["replay_rejected"]), _fmt(r["tamper_rejected"]), _fmt(r["psnr_mod"]),
                 _fmt(r["psnr_worst"]), f"{_fmt(r['frames_mod'])}/{_fmt(r['frames'])}", _fmt(r["ssim"], 5),
                 _fmt(r["embed_s"], 0), _fmt(r["verify_s"], 0)] for r in e2e]
        sections += ["## End-to-end runs\n", _markdown(headers, rows)]
        tables["e2e"] = _latex(headers, rows, "End-to-end embedding and video-only verification.", "tab:e2e")

    capacity = capacity_rows()
    if capacity:
        headers = ["Video", "Frames", "Min bits/100 fr.", "Mean bits/100 fr.", "Total bits", "Registered fits",
                   "In-band fits"]
        rows = [[r["video"], _fmt(r["frames"]), _fmt(r["bits_per_100_frames_min"]),
                 _fmt(r["bits_per_100_frames_mean"], 0), _fmt(r["total_bits"]), _fmt(r["registered_fits"]),
                 _fmt(r["in_band_fits"])] for r in capacity]
        sections += ["## Carrier capacity\n", _markdown(headers, rows)]
        tables["capacity"] = _latex(headers, rows, "Stable, patchability-checked carrier capacity.",
                                    "tab:capacity")

    steg = _load("steg_*.json")
    if steg:
        headers = ["Case", "PoV P(embed) cover", "PoV P(embed) stego", "Magnitude hist. p", "T1 sign p",
                   "SPA cover", "SPA stego"]
        rows = [[stem.removeprefix("steg_"),
                 _fmt(r["pairs_of_values_attack"]["cover"]["embedding_probability"], 3),
                 _fmt(r["pairs_of_values_attack"]["stego"]["embedding_probability"], 3),
                 _fmt(r["magnitude_histogram"]["p_value"], 3), _fmt(r["trailing_one_signs"]["p_value"], 3),
                 _fmt(r["pixel_reference_detectors"]["spa_cover"], 5),
                 _fmt(r["pixel_reference_detectors"]["spa_stego"], 5)] for stem, r in steg.items()]
        sections += ["## Targeted classical steganalysis\n", _markdown(headers, rows)]
        tables["steg_classical"] = _latex(headers, rows, "Targeted classical steganalysis against the exact cover.",
                                          "tab:steg-classical")

    ml_path = RESULTS / "ml_eval.json"
    if ml_path.exists():
        ml = json.loads(ml_path.read_text(encoding="utf-8"))
        headers = ["Protocol", "Features / detector", "P_E", "AUC"]
        rows = [[protocol, name, _fmt(result["p_e_mean"], 3), _fmt(result["auc_mean"], 3)]
                for protocol, results in ml["protocols"].items() for name, result in results.items()]
        sections += [f"## Learned steganalysis ({ml['frame_pairs']} frame pairs, clips: "
                     f"{', '.join(ml['clips'])})\n", _markdown(headers, rows)]
        tables["steg_ml"] = _latex(headers, rows, "Learned steganalysis on modified frames (P\\_E = 0.5 is chance).",
                                   "tab:steg-ml")

    cnn = cnn_rows()
    if cnn:
        headers = ["Carrier", "Protocol", "Change", "Pairs", "Seeds", "P_E frame", "AUC frame",
                   "P_E full frame", "P_E segment"]
        rows = [[r["carrier"], r["protocol"], r["change"], _fmt(r["pairs"]), _fmt(r["seeds"]),
                 r["p_e"], r["auc"], r["p_e_full"], r["p_e_segment"]] for r in cnn]
        sections += ["## CNN steganalysis\n", _markdown(headers, rows)]
        tables["steg_cnn"] = _latex(
            headers, rows,
            "CNN steganalysis (SRM front end, Yedroudj-style); P\\_E = 0.5 is chance. Ranges are over "
            "seeds; amplified rows scale the real change to give a detection margin.",
            "tab:steg-cnn")

    adaptive = adaptive_rows()
    if adaptive:
        headers = ["Clip", "Coding", "Carriers", "Changes", "Changes/bit", "PSNR mod. (dB)", "Worst (dB)",
                   "Embed (s)", "Verify (s)"]
        rows = [[r["clip"], r["mode"], _fmt(r["carriers"]), _fmt(r["changes"]), _fmt(r["per_bit"], 3),
                 _fmt(r["psnr_mod"]), _fmt(r["psnr_worst"]), _fmt(r["embed_s"], 0), _fmt(r["verify_s"], 0)]
                for r in adaptive["runs"]]
        sections += ["## Syndrome-trellis coded carriers\n", _markdown(headers, rows)]
        tables["adaptive_e2e"] = _latex(
            headers, rows, "Direct vs.\\ syndrome-trellis coded magnitude carriers (registered envelope, "
            "200-frame CIF QP\\,22 cuts); every run verifies from the video alone.", "tab:adaptive-e2e")
    if adaptive and adaptive["detection"]:  # empty when learned steganalysis was deferred
        headers = ["Protocol", "Features / detector"] + adaptive["modes"]
        rows = [[protocol, name] + [_fmt(value, 3) for value in values]
                for (protocol, name), values in adaptive["detection"].items()]
        sections += ["## Learned steganalysis, direct vs. STC\n", _markdown(headers, rows)]
        tables["adaptive_steg"] = _latex(
            headers, rows, "Learned steganalysis $P_E$ for direct and syndrome-trellis coded carriers "
            "(" + str(adaptive["frame_pairs"]) + " frame pairs per mode).", "tab:adaptive-steg")

    gop_path = RESULTS / "gop_summary.json"
    if gop_path.exists():
        gop = [row for row in json.loads(gop_path.read_text(encoding="utf-8")) if row.get("verified")]
        cases_path = ROOT / "benchmark" / "latticezk_gop_cases.json"
        frames = ({case["name"]: case["frames"] for case in json.loads(cases_path.read_text(encoding="utf-8"))}
                  if cases_path.exists() else {})
        headers = ["Clip", "GOP", "Frames", "Envelope (B)", "kbit/100 fr.", "P-slice tamper rej.",
                   "Frames mod.", "PSNR all (dB)", "PSNR mod. (dB)", "Worst (dB)", "Embed (s)", "Verify (s)"]
        rows = [[r["clip"], _fmt(r["gop"]), _fmt(frames.get(r["name"])), _fmt(r.get("e2e_envelope_bytes")),
                 _fmt(r["carrier_bits_per_100_frames"] / 1000, 1), _fmt(r.get("p_slice_tamper_rejected")),
                 _fmt(r["frames_modified"]), _fmt(r["luma_psnr_all_frames_db"]),
                 _fmt(r["luma_psnr_modified_frames_db"]), _fmt(r["luma_psnr_worst_frame_db"]),
                 _fmt(r["embed_s"], 0), _fmt(r["verify_s"], 0)]
                for r in sorted(gop, key=lambda r: (r.get("e2e_envelope_bytes") or 0, r["clip"], r["gop"]))]
        sections += ["## GOP > 1 (IDR carriers, P slices bound raw)\n", _markdown(headers, rows)]
        tables["gop"] = _latex(
            headers, rows, "GOP $>1$ streams: carriers in IDR slices only, P slices bound byte for byte "
            "(CIF, QP\\,22, registered). The 413-byte rows use the toy parameter set to fit short clips; "
            "the larger rows use the production set on looped sources.", "tab:gop")

    baselines = sorted(RESULTS.glob("baselines*.json"))
    if baselines:
        base = json.loads(baselines[-1].read_text(encoding="utf-8"))
        bdlop, groth, isw = base["bdlop_open_128"], base["groth16_bn128"], base["isw21_recorded"]
        headers = ["Scheme", "PQ", "ZK", "In-video bytes", "Prove (ms)", "Verify (ms)", "Setup"]
        rows = [
            ["BDLOP (this work, registered)", "yes", "yes", _fmt(bdlop["in_video_envelope_bytes"]["registered"]),
             _fmt(bdlop["timings_ms"]["prove"]["median"], 0), _fmt(bdlop["timings_ms"]["verify"]["median"], 1),
             "transparent"],
            ["BDLOP (this work, in-band)", "yes", "yes", _fmt(bdlop["in_video_envelope_bytes"]["in_band"]),
             _fmt(bdlop["timings_ms"]["prove"]["median"], 0), _fmt(bdlop["timings_ms"]["verify"]["median"], 1),
             "transparent"],
            ["Groth16 (BN128)", "no", "yes", _fmt(groth.get("proof_bearing_payload_bytes")),
             _fmt(groth.get("prove_time_ms"), 0), _fmt(groth.get("verify_time_ms"), 0), "trusted, per circuit"],
            ["ML-DSA-44 (signature)", "yes", "no", _fmt(base["ml_dsa"]["ml_dsa_44"]["signature_bytes"]),
             _fmt(base["ml_dsa"]["ml_dsa_44"]["sign"]["median_ms"], 1),
             _fmt(base["ml_dsa"]["ml_dsa_44"]["verify"]["median_ms"], 2), "none"],
            ["ISW21 (recorded)", "broken KS assumption", "stat. 2^-40", _fmt(isw["in_video_envelope_bytes"]),
             _fmt(isw["prove_ms"], 0), _fmt(isw["verify_ms"], 1), "trusted, designated verifier"],
        ]
        sections += ["## Baselines\n", _markdown(headers, rows)]
        tables["baselines"] = _latex(headers, rows, "Comparison with baseline proof and signature schemes.",
                                     "tab:baselines")

    (PAPER / "tables").mkdir(parents=True, exist_ok=True)
    for name, tex in tables.items():
        (PAPER / "tables" / f"{name}.tex").write_text(tex, encoding="utf-8")
    _figures(e2e, capacity)
    summary = "\n".join(sections)
    (RESULTS / "SUMMARY.md").write_text(summary, encoding="utf-8")
    return summary


def _figures(e2e: list[dict[str, Any]], capacity: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    (PAPER / "figures").mkdir(parents=True, exist_ok=True)
    if capacity:
        ordered = sorted(capacity, key=lambda row: row["bits_per_100_frames_mean"])
        figure, axis = plt.subplots(figsize=(6, 3))
        axis.barh([row["video"].split("_q")[0] for row in ordered],
                  [row["bits_per_100_frames_mean"] / 1000 for row in ordered], color="#4c72b0")
        for threshold, label in ((_envelope_bits(True) / 3 / 1000, "registered, 300 frames"),
                                 (_envelope_bits(False) / 3 / 1000, "in-band, 300 frames")):
            axis.axvline(threshold, linestyle="--", color="#c44e52" if "in" in label else "#55a868", label=label)
        axis.set_xlabel("Carrier capacity (kbit per 100 frames)")
        axis.legend(fontsize=7, loc="lower right")
        figure.tight_layout()
        figure.savefig(PAPER / "figures" / "capacity.pdf")
        plt.close(figure)
    if e2e:
        figure, axis = plt.subplots(figsize=(6, 3))
        labels = [row["case"] for row in e2e]
        axis.bar(labels, [row["psnr_mod"] or 0 for row in e2e], color="#4c72b0", label="modified frames")
        axis.scatter(labels, [row["psnr_worst"] or 0 for row in e2e], color="#c44e52", zorder=3, label="worst frame")
        axis.set_ylabel("Luma PSNR vs. cover (dB)")
        axis.tick_params(axis="x", rotation=45, labelsize=7)
        axis.legend(fontsize=7)
        figure.tight_layout()
        figure.savefig(PAPER / "figures" / "quality.pdf")
        plt.close(figure)


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    sys.stdout.write(build())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
