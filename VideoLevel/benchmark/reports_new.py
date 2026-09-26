"""Create named, human-readable PDF summaries from *_new.json run records."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"


def _page_header(pdf: PdfPages, title: str, subtitle: str) -> plt.Figure:
    fig = plt.figure(figsize=(11.7, 8.3))
    fig.text(0.06, 0.94, title, fontsize=20, weight="bold", va="top")
    fig.text(0.06, 0.895, subtitle, fontsize=9, color="#444444", va="top", wrap=True)
    return fig


def _table_page(pdf: PdfPages, title: str, subtitle: str,
                headers: list[str], rows: list[list[str]], font_size: int = 7) -> None:
    fig = _page_header(pdf, title, subtitle)
    ax = fig.add_axes([0.04, 0.05, 0.92, 0.78])
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=headers, loc="upper left", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    table.scale(1.0, 1.38)
    for (row, _col), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#d9eaf7")
            cell.set_text_props(weight="bold")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _finite(value: Any, digits: int = 3) -> str:
    try:
        x = float(value)
        return f"{x:.{digits}f}" if math.isfinite(x) else "∞"
    except (TypeError, ValueError):
        return "—"


def build_media_pdf(record: dict[str, Any], destination: Path,
                    conversion_record: dict[str, Any] | None = None) -> None:
    results = record.get("results", [])
    passed = [r for r in results if r.get("status") == "passed"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        subtitle = ("Real Y4M→H.264→native CAVLC embed→blind extraction→strict decode runs. "
                    "Higher resolutions are scaled from CIF and must not be interpreted as native high-resolution scenes.")
        _table_page(pdf, "Video pipeline benchmark (new)", subtitle,
                    ["Source", "Resolution", "Sample fr", "Source fr", "Full sec", "Encode ms", "Capacity ms", "Embed ms", "CPU s", "FPS*", "RSS MB", "Gate"],
                    [[r.get("source", "?"), r.get("resolution", "?"), str(r.get("encoded_frames", "?")), str(r.get("source_frames", "?")),
                      _finite(r.get("source_duration_seconds"), 1), _finite(r.get("encode_ms"), 1),
                      _finite(r.get("capacity_measurement_ms"), 1), _finite(r.get("embed_ms"), 1),
                      _finite(r.get("embed_cpu_seconds_sampled"), 3), _finite(r.get("output_fps"), 1),
                      _finite((r.get("embed_peak_rss_bytes_sampled") or 0) / 1e6, 1), r.get("status", "failed")]
                     for r in results[:20]], 6)
        for offset in range(20, len(results), 20):
            _table_page(pdf, "Video pipeline benchmark (new) — continued", subtitle,
                        ["Source", "Resolution", "Sample fr", "Source fr", "Full sec", "Encode ms", "Capacity ms", "Embed ms", "CPU s", "FPS*", "RSS MB", "Gate"],
                        [[r.get("source", "?"), r.get("resolution", "?"), str(r.get("encoded_frames", "?")), str(r.get("source_frames", "?")),
                          _finite(r.get("source_duration_seconds"), 1), _finite(r.get("encode_ms"), 1),
                          _finite(r.get("capacity_measurement_ms"), 1), _finite(r.get("embed_ms"), 1),
                          _finite(r.get("embed_cpu_seconds_sampled"), 3), _finite(r.get("output_fps"), 1),
                          _finite((r.get("embed_peak_rss_bytes_sampled") or 0) / 1e6, 1), r.get("status", "failed")]
                         for r in results[offset:offset + 20]], 6)
        if passed:
            labels = [f"{r['source'].replace('_cif.y4m','')}\n{r['resolution']}" for r in passed]
            fig = _page_header(pdf, "Embedding performance and resource use", "*Output FPS = encoded frames / native embed wall time; not sensor/camera acquisition FPS. RSS and CPU are sampled only for the native embed child.")
            ax = fig.add_axes([0.08, 0.16, 0.88, 0.65])
            fps = [r.get("output_fps") or 0 for r in passed]
            rss = [(r.get("embed_peak_rss_bytes_sampled") or 0) / 1e6 for r in passed]
            pos = np.arange(len(labels))
            ax.bar(pos - 0.2, fps, 0.4, label="embed frames/sec", color="#247ba0")
            ax.set_ylabel("Frames/sec")
            ax.set_xticks(pos, labels, rotation=70, ha="right", fontsize=6)
            ax2 = ax.twinx()
            ax2.plot(pos + 0.2, rss, "o", color="#d1495b", label="sampled peak RSS MB")
            ax2.set_ylabel("Sampled peak RSS (MB)")
            ax.legend(loc="upper left")
            ax2.legend(loc="upper right")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
            quality_rows = []
            for r in passed:
                q = r.get("quality", {})
                psnr = q.get("source_to_stego_psnr_y", {})
                ssim = q.get("source_to_stego_ssim", {})
                dpsnr = q.get("cover_to_stego_psnr_y", {})
                dssim = q.get("cover_to_stego_ssim", {})
                quality_rows.append([r["source"], r["resolution"], str(psnr.get("frames_measured", "—")),
                                     _finite(psnr.get("mean_finite")), _finite(psnr.get("min_finite")),
                                     _finite(ssim.get("mean_finite"), 6), _finite(ssim.get("min_finite"), 6),
                                     _finite(dpsnr.get("min_finite")), _finite(dssim.get("min_finite"), 6)])
            _table_page(pdf, "Per-frame visual quality summary", "Raw-source comparison includes H.264 compression plus embedding. Cover-to-stego isolates embedding impact. Full per-frame PSNR/SSIM measurements are in quality_per_frame_new.csv.",
                        ["Source", "Size", "Frames", "Source PSNR μ", "PSNR min", "Source SSIM μ", "SSIM min", "Embed PSNR min", "Embed SSIM min"],
                        quality_rows, 6)
        _table_page(pdf, "Scope and acceptance", "Benchmark status and reproducibility boundaries.",
                    ["Item", "Value"], [["Pass gate", "native embed + strict FFmpeg decode + blind correct-key recovery + wrong-key rejection"],
                                         ["Source corpus", ", ".join(record.get("methodology", {}).get("source_files", []))],
                                         ["Encoding", record.get("methodology", {}).get("encoding", "")],
                                         ["Quality metric", record.get("methodology", {}).get("quality", "")],
                                         ["ZKP scope", record.get("methodology", {}).get("zkp_boundary", "")],
                                         ["Run count", f"{len(passed)} passed / {len(results)} total"],
                                         ["Run ID", str(record.get("run_id", "unknown"))]], 8)
        conversion_rows = (conversion_record or {}).get("results", [])
        if conversion_rows:
            _table_page(pdf, "Full-duration Y4M to H.264 conversion (new)",
                        "All source frames are encoded at each Y4M file's native resolution. This is distinct from the bounded 30-frame, multi-resolution embedding matrix.",
                        ["Source", "Resolution", "Frames", "Duration s", "Encode ms", "H.264 bytes", "Output FPS", "Gate"],
                        [[item.get("source", "?"), item.get("resolution", "?"), str(item.get("source_frames", "?")),
                          _finite(item.get("source_duration_seconds"), 2), _finite(item.get("encode_ms"), 1),
                          str(item.get("output_bytes", "?")),
                          _finite(item.get("source_frames", 0) * 1000 / item.get("encode_ms", 1), 1), item.get("status", "failed")]
                         for item in conversion_rows], 7)


def build_quality_pdf(record: dict[str, Any], destination: Path) -> None:
    results = record.get("results", [])
    destination.parent.mkdir(parents=True, exist_ok=True)
    subtitle = ("Per-frame Y-PSNR and SSIM from the recorded sample window. Source→stego includes H.264 encode + embedding; "
                "cover→stego isolates incremental embedding impact. The 40 dB mark is a reference quality floor, "
                "not part of the functional pass gate. Upscaled cases originate from CIF content.")
    rows = []
    for item in results:
        quality = item.get("quality", {})
        source_psnr = quality.get("source_to_stego_psnr_y", {})
        source_ssim = quality.get("source_to_stego_ssim", {})
        delta_psnr = quality.get("cover_to_stego_psnr_y", {})
        delta_ssim = quality.get("cover_to_stego_ssim", {})
        min_embed_psnr = delta_psnr.get("min_finite")
        rows.append([item.get("source", "?"), item.get("resolution", "?"),
                     str(source_psnr.get("frames_measured", "—")),
                     _finite(source_psnr.get("mean_finite")), _finite(source_psnr.get("min_finite")),
                     _finite(source_ssim.get("mean_finite"), 6), _finite(source_ssim.get("min_finite"), 6),
                     _finite(min_embed_psnr), _finite(delta_ssim.get("min_finite"), 6),
                     "yes" if min_embed_psnr is not None and min_embed_psnr >= 40 else "NO",
                     item.get("status", "failed")])
    with PdfPages(destination) as pdf:
        page_size = 22
        for offset in range(0, max(1, len(rows)), page_size):
            _table_page(pdf, "Video image quality (new)" if offset == 0 else "Video image quality (new) — continued",
                        subtitle, ["Source", "Resolution", "Frames", "Source PSNR μ", "PSNR min",
                                   "Source SSIM μ", "SSIM min", "Embed PSNR min", "Embed SSIM min", "Ref 40 dB", "Pipeline"],
                        rows[offset:offset + page_size], 7)
        _table_page(pdf, "Per-frame quality artifact", "Each frame's raw values and finite/infinite PSNR handling are in the CSV emitted with this media run.",
                    ["Field", "Meaning"], [["Source→stego", "Y-PSNR and SSIM relative to decoded Y4M at the output resolution; includes lossy encode."],
                                             ["Cover→stego", "Y-PSNR and SSIM relative to clean H.264 decode; isolates changes from embedding."],
                                             ["Sample", f"At most {record.get('methodology', {}).get('max_frames_per_case')} initial frames per source/resolution; full-duration H.264 conversions are separately manifested."],
                                             ["Raw values", str(record.get("frame_quality_csv", "quality_per_frame_new.csv"))]], 8)


def build_security_pdf(record: dict[str, Any], destination: Path) -> None:
    results = record.get("results", [])
    names = list(dict.fromkeys(row["algorithm"] for row in results))
    sizes = sorted({row["payload_bytes"] for row in results})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        _table_page(pdf, "Cryptographic payload alternatives (new)",
                    "Actual cryptography-library implementations. HMAC is the current-proposal component reference, not a native timing/overhead measurement; rows with different properties are not drop-in equivalent.",
                    ["Algorithm", "Role", "Category", "Bytes", "Seal μ ms", "Seal p95", "Open/verify μ", "Extra bytes", "Tamper reject"],
                    [[r["algorithm"], "This Work ref." if r.get("role") == "this_work_component_reference" else "Comparison",
                      r["category"], str(r["payload_bytes"]), _finite(r["seal_ms_median"], 4),
                      _finite(r["seal_ms_p95"], 4), _finite(r["open_verify_ms_median"], 4),
                      str(r["overhead_bytes"]), str(r["tamper_rejected"])] for r in results], 6)
        for size in sizes:
            fig = _page_header(pdf, f"Seal and open/verify timing — {size} byte payload", "Measured on this host with generated one-run keys and real operations; not literature values.")
            ax = fig.add_axes([0.11, 0.19, 0.82, 0.65])
            subset = [r for r in results if r["payload_bytes"] == size]
            x = np.arange(len(names))
            seal = [next((r["seal_ms_median"] for r in subset if r["algorithm"] == n), 0) for n in names]
            verify = [next((r["open_verify_ms_median"] for r in subset if r["algorithm"] == n), 0) for n in names]
            ax.bar(x - 0.18, seal, 0.36, label="seal/sign", color="#247ba0")
            ax.bar(x + 0.18, verify, 0.36, label="open/verify", color="#f3a712")
            ax.set_yscale("log")
            ax.set_ylabel("Median milliseconds (log scale)")
            ax.set_xticks(x, names, rotation=48, ha="right", fontsize=7)
            ax.legend()
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
        prop_rows = []
        for name in names:
            r = next(row for row in results if row["algorithm"] == name)
            p = r["properties"]
            prop_rows.append([name, str(p["confidentiality"]), str(p["integrity"]),
                              str(p["shared_key_authentication"]), str(p["public_verifiability"]), r["notes"]])
        _table_page(pdf, "Security properties and non-equivalence", "True means provided under the listed key-management assumptions; this table is not a certification or formal security proof.",
                    ["Algorithm", "Confidentiality", "Integrity", "Shared-key / peer auth", "Public verify", "Assumptions / scope"], prop_rows, 6)
        mapping = record.get("proposal_mapping", {})
        _table_page(pdf, "This Work / proposal baseline", "This page distinguishes the current native video proposal from primitive-only comparison rows.",
                    ["Layer", "Current proposal and benchmark scope"],
                    [["Video carrier", "Modify H.264 CAVLC coefficients in the native compressed-domain path; media benchmark exercises this path."],
                     ["Authentication", mapping.get("this_work", "Not recorded")],
                     ["Crypto table HMAC row", mapping.get("hmac_row_scope", "Not recorded")],
                     ["ZKP relation", mapping.get("zkp_scope", "Not recorded")]], 8)
        _table_page(pdf, "Signcryption scope", "No standardized signcryption primitive is available in the installed crypto stack. The real measured X25519+AEAD and Ed25519+AEAD composition is labeled precisely and must not be reported as formal signcryption.",
                    ["Item", "Benchmark treatment"], [["X25519 + HKDF + ChaCha20-Poly1305", "Actually executed authenticated public-key encryption with pre-authenticated static sender identity; no non-repudiation."],
                                                       ["X25519 AEAD + Ed25519 detached signature", "Actually executed encrypt-then-sign composition; publicly verifiable, higher overhead, but not a formal signcryption construction."],
                                                       ["HMAC-SHA-256", "Current native CAVLC stream authenticator; integrity/origin among key holders only; no encryption."],
                                                       ["AES-GCM / ChaCha20-Poly1305", "Shared-key confidentiality and integrity; identity depends on key distribution."],
                                                       ["RSA-PSS / Ed25519", "Publicly verifiable signatures, but payload is not confidential."],
                                                       ["RSA-OAEP + AES-GCM", "Public-key recipient confidentiality; does not authenticate the sender."]], 8)


def build_zkp_pdf(record: dict[str, Any], destination: Path) -> None:
    rows = record.get("results", [])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(destination) as pdf:
        _table_page(pdf, "Zero-knowledge proof systems (new)",
                    "Actual Groth16 and PLONK proofs generated and verified against the same Circom R1CS statement and common witness.",
                    ["System", "Trial", "Witness ms", "Prove ms", "Verify ms", "JSON proof B", "Compact B", "RSS prove MB", "Valid", "Tamper rejected"],
                    [[r["algorithm"], str(r["trial"]), _finite(r.get("witness_ms"), 1), _finite(r["prove_ms"], 1), _finite(r["verify_ms"], 1),
                      str(r["serialized_proof_json_bytes"]), str(r.get("compact_proof_bytes") or "—"),
                      _finite((r.get("prove_peak_rss_bytes_sampled") / 1e6) if r.get("prove_peak_rss_bytes_sampled") is not None else None, 1),
                      str(r["proof_valid"]), str(r["tampered_public_input_rejected"])] for r in rows], 8)
        if rows:
            names = list(dict.fromkeys(r["algorithm"] for r in rows))
            means = [np.mean([r["prove_ms"] for r in rows if r["algorithm"] == name]) for name in names]
            fig = _page_header(pdf, "Measured prove time", "PLONK setup is reported separately and excluded from steady-state prove latency.")
            ax = fig.add_axes([0.16, 0.18, 0.7, 0.66])
            ax.bar(names, means, color=["#247ba0", "#d1495b"][:len(names)])
            ax.set_ylabel("Prove time (ms)")
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)
        limitations = [["Same statement", record.get("statement", "")],
                       ["Constraints", str(record.get("circuit_constraints", "—"))],
                       ["PLONK setup", f"{_finite(record.get('plonk_setup_ms'), 1)} ms"],
                       ["Provenance", "Groth16 proving artifact ceremony provenance not independently certified."],
                       ["Not measured", "Halo2, RISC Zero/STARK, Bulletproofs, and other systems are unimplemented; do not substitute literature or legacy simulated values."],
                       ["Proof boundary", "Proof concerns circuit relation, not camera origin or complete H.264 integrity."]]
        _table_page(pdf, "Setup, trust and scope limits", "Only measured facts are plotted. Any unimplemented alternative remains unmeasured.", ["Scope", "Details"], limitations, 8)


def build_reports(results_dir: Path = RESULTS) -> list[Path]:
    created: list[Path] = []
    media_runs = sorted((results_dir / "media_new").glob("*/video_pipeline_new.json"))
    if media_runs:
        latest = json.loads(media_runs[-1].read_text(encoding="utf-8"))
        conversion_path = results_dir / "conversion_manifest_new.json"
        conversion = json.loads(conversion_path.read_text(encoding="utf-8")) if conversion_path.is_file() else None
        path = results_dir / "performance_new.pdf"
        build_media_pdf(latest, path, conversion)
        created.append(path)
        path = results_dir / "video_quality_new.pdf"
        build_quality_pdf(latest, path)
        created.append(path)
    security = results_dir / "security_new.json"
    if security.is_file():
        path = results_dir / "security_new.pdf"
        build_security_pdf(json.loads(security.read_text(encoding="utf-8")), path)
        created.append(path)
    zkp = results_dir / "zkp_new.json"
    if zkp.is_file():
        path = results_dir / "zkp_new.pdf"
        build_zkp_pdf(json.loads(zkp.read_text(encoding="utf-8")), path)
        created.append(path)
    return created


if __name__ == "__main__":
    for item in build_reports():
        print(item)
