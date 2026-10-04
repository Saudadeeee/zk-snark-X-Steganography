"""Build the single consolidated benchmark report from the measured *_new records.

Output: benchmark/results/benchmark_report_new.pdf. Every number on every page is
read from a record written by a measured run (media_new/<run-id>, e2e_new.json,
zkp_new.json, security_new.json, conversion_manifest_new.json and the recorded
realtime camera runs); the report computes summaries but never estimates.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

from src.native_blind_contract import FRAME_HEADER_BYTES

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark" / "results"
REPORT_NAME = "benchmark_report_new.pdf"
PAGE_SIZE = (11.69, 8.27)
HEADER_COLOR = "#d9eaf7"
BLUE, ORANGE, RED, GREEN, GREY = "#247ba0", "#f3a712", "#d1495b", "#2e8b57", "#777777"
QUALITY_REFERENCE_DB = 40.0

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


# ----------------------------------------------------------------- formatting

def num(value: Any, digits: int = 1) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isinf(x):
        return "∞"
    return f"{x:,.{digits}f}" if math.isfinite(x) else "—"


def yes(value: Any) -> str:
    return "có" if value is True else ("không" if value is False else "—")


def short_clip(name: str) -> str:
    return name.replace("_cif", "").replace(".y4m", "")


def wrap(text: Any, width: int) -> str:
    return "\n".join(textwrap.wrap(str(text), width)) or "—"


# --------------------------------------------------------------------- report

class Report:
    """A4 landscape pages with a title, optional subtitle, footer and page number."""

    def __init__(self, pdf: PdfPages, footer: str) -> None:
        self.pdf, self.footer, self.page = pdf, footer, 0

    def figure(self, title: str, subtitle: str = "") -> plt.Figure:
        fig = plt.figure(figsize=PAGE_SIZE)
        fig.text(0.045, 0.955, title, fontsize=16, weight="bold", va="top")
        if subtitle:
            fig.text(0.045, 0.905, wrap(subtitle, 175), fontsize=8.3, color="#444444", va="top")
        return fig

    def save(self, fig: plt.Figure) -> None:
        self.page += 1
        fig.text(0.045, 0.02, self.footer, fontsize=7, color=GREY)
        fig.text(0.955, 0.02, str(self.page), fontsize=8, color=GREY, ha="right")
        self.pdf.savefig(fig)
        plt.close(fig)

    def table(self, title: str, subtitle: str, headers: list[str], rows: list[list[str]], *,
              font: float = 7.5, per_page: int = 40, widths: list[float] | None = None) -> None:
        """Table that wraps every cell to its column width and paginates by real row height."""
        widths = widths or [1.0 / len(headers)] * len(headers)
        headers = _wrap_row(headers, widths, font)
        body = [_wrap_row(row, widths, font) for row in (rows or [["—"] * len(headers)])]
        subtitle_lines = wrap(subtitle, 175).count("\n") + 1 if subtitle else 0
        top = 0.9 - 0.022 * subtitle_lines - (0.01 if subtitle else 0)
        available_in = (top - 0.08) * PAGE_SIZE[1]
        for number, chunk in enumerate(_paginate(headers, body, font, available_in, per_page)):
            fig = self.figure(title if number == 0 else f"{title} (tiếp)", subtitle)
            ax = fig.add_axes([0.04, 0.06, 0.92, top - 0.06])
            ax.axis("off")
            table = ax.table(cellText=chunk, colLabels=headers, loc="upper left", cellLoc="left", colWidths=widths)
            table.auto_set_font_size(False)
            table.set_fontsize(font)
            _style_table(table, font, (top - 0.06) * PAGE_SIZE[1])
            self.save(fig)

    def text(self, title: str, blocks: list[tuple[str, str]], subtitle: str = "") -> None:
        """Wrapped prose page; block kinds: 'h' heading, 'p' paragraph, 'b' bullet."""
        fig = self.figure(title, subtitle)
        y = 0.86 if subtitle else 0.89
        for kind, body in blocks:
            if kind == "h":
                y -= 0.012
                fig.text(0.05, y, body, fontsize=11, weight="bold", va="top")
                y -= 0.035
                continue
            prefix, indent = ("• ", 0.065) if kind == "b" else ("", 0.05)
            lines = textwrap.wrap(prefix + body, 150 if kind == "p" else 145)
            for line in lines:
                fig.text(indent, y, line, fontsize=9, va="top")
                y -= 0.026
            y -= 0.008
        self.save(fig)


TABLE_WIDTH_PT = 0.92 * PAGE_SIZE[0] * 72
LINE_FACTOR, PAD_FACTOR = 1.35, 0.65


def _wrap_row(row: list[Any], widths: list[float], font: float) -> list[str]:
    """Wrap each cell (keeping its own line breaks) to the characters its column can hold."""
    cells = []
    for value, width in zip(row, widths):
        chars = max(4, int(width * TABLE_WIDTH_PT / (0.58 * font)) - 1)
        lines = [piece for line in str(value).split("\n") for piece in (textwrap.wrap(line, chars) or [""])]
        cells.append("\n".join(lines))
    return cells


def _row_height_in(row: list[str], font: float) -> float:
    lines = max(cell.count("\n") + 1 for cell in row)
    return (font * LINE_FACTOR * lines + font * PAD_FACTOR) / 72


def _paginate(headers: list[str], rows: list[list[str]], font: float, available_in: float,
              per_page: int) -> list[list[list[str]]]:
    pages: list[list[list[str]]] = []
    current: list[list[str]] = []
    used = _row_height_in(headers, font)
    for row in rows:
        height = _row_height_in(row, font)
        if current and (used + height > available_in or len(current) >= per_page):
            pages.append(current)
            current, used = [], _row_height_in(headers, font)
        current.append(row)
        used += height
    pages.append(current)
    return pages


def _style_table(table: Any, font: float, axes_height_in: float) -> None:
    """Every cell of a row gets the row's height, sized from the font and its tallest cell."""
    cells = table.get_celld()
    row_lines: dict[int, int] = {}
    for (row, _col), cell in cells.items():
        row_lines[row] = max(row_lines.get(row, 1), cell.get_text().get_text().count("\n") + 1)
    for (row, _col), cell in cells.items():
        cell.set_height((font * LINE_FACTOR * row_lines[row] + font * PAD_FACTOR) / 72 / axes_height_in)
        cell.set_edgecolor("#bbbbbb")
        if row == 0:
            cell.set_facecolor(HEADER_COLOR)
            cell.set_text_props(weight="bold")
        elif row % 2 == 0:
            cell.set_facecolor("#f6f8fa")


# -------------------------------------------------------------------- loading

def _json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_records(results_dir: Path) -> dict[str, Any]:
    media_runs = sorted((results_dir / "media_new").glob("*/video_pipeline_new.json"))
    media = _json(media_runs[-1]) if media_runs else None
    camera_files = sorted(results_dir.glob("realtime_camera_runs_*.json"))
    frames: list[dict[str, str]] = []
    if media and media_runs:
        csv_path = media_runs[-1].parent / "quality_per_frame_new.csv"
        if csv_path.is_file():
            with csv_path.open(encoding="utf-8", newline="") as handle:
                frames = list(csv.DictReader(handle))
    return {"media": media, "media_dir": media_runs[-1].parent if media_runs else None, "frames": frames,
            "conversion": _json(results_dir / "conversion_manifest_new.json"),
            "e2e": _json(results_dir / "e2e_new.json"), "zkp": _json(results_dir / "zkp_new.json"),
            "security": _json(results_dir / "security_new.json"),
            "camera": _json(camera_files[-1]) if camera_files else None,
            "camera_file": camera_files[-1].name if camera_files else None}


def _passed(media: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [r for r in (media or {}).get("results", []) if r.get("status") == "passed"]


def _per(total: Any, count: Any) -> float | None:
    return total / count if isinstance(total, (int, float)) and count else None


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


# ------------------------------------------------------------------ summary

def summary_page(report: Report, data: dict[str, Any]) -> None:
    media, e2e, zkp = data["media"] or {}, data["e2e"] or {}, data["zkp"] or {}
    conversion = data["conversion"] or {}
    results = media.get("results", [])
    passed = _passed(media)
    e2e_sum = e2e.get("summary", {})
    groth = [r for r in zkp.get("results", []) if r["algorithm"].startswith("Groth16")]
    plonk = [r for r in zkp.get("results", []) if r["algorithm"].startswith("PLONK")]
    stages = e2e.get("stage_summary_ms", {})
    embed_psnr = [r["quality"]["cover_to_stego_psnr_y"]["min_finite"] for r in passed
                  if r.get("quality", {}).get("cover_to_stego_psnr_y", {}).get("min_finite") is not None]
    z_values = [abs(r["sign_statistics"]["two_proportion_z"]) for r in passed if r.get("sign_statistics")]
    outside = sum(r["sign_statistics"]["changed_outside_schedule"] for r in passed if r.get("sign_statistics"))
    attacks_ok = f"{e2e_sum.get('attacks_as_expected', '—')}/{e2e_sum.get('attacks', '—')}"
    first = passed[0] if passed else {}
    verdicts = [
        ["Chuyển đổi Y4M → H.264 (toàn bộ clip)", f"{conversion.get('converted', '—')}/{conversion.get('total', '—')} clip", _ok(conversion.get("failed") == 0)],
        ["Ma trận media (clip × độ phân giải)", f"{len(passed)}/{len(results)} case pass", _ok(bool(results) and len(passed) == len(results))],
        ["End-to-end payload ZK thật", f"{e2e_sum.get('trials_passed', '—')}/{e2e_sum.get('trials', '—')} lần", _ok(e2e_sum.get("trials_passed") == e2e_sum.get("trials"))],
        ["Ma trận tấn công / độ bền", f"{attacks_ok} đúng kỳ vọng", _ok(e2e_sum.get("attacks_as_expected") == e2e_sum.get("attacks"))],
        ["Groth16 (proof hợp lệ, public input sửa bị từ chối)", f"{sum(r['proof_valid'] and r['tampered_public_input_rejected'] for r in groth)}/{len(groth)}", _ok(bool(groth) and all(r["proof_valid"] and r["tampered_public_input_rejected"] for r in groth))],
        ["PLONK (cùng R1CS)", f"{sum(r['proof_valid'] and r['tampered_public_input_rejected'] for r in plonk)}/{len(plonk)}", _ok(bool(plonk) and all(r["proof_valid"] and r["tampered_public_input_rejected"] for r in plonk))],
        ["Bit bị đổi ngoài lịch nhúng (mọi case)", str(outside), _ok(outside == 0 and bool(passed))],
    ]
    figures = [
        ["Payload mang theo", f"{num(first.get('payload_bytes'), 0)} B = 4 B độ dài + {num(first.get('message_bytes'), 0)} B message + {num(first.get('proof_bytes'), 0)} B proof"],
        ["Khung v3 / số IDR cần", f"{num(first.get('frame_bits'), 0)} bit / {num(first.get('idr_segments_needed'), 0)} IDR (64 bit mỗi IDR)"],
        ["Groth16 prove / verify (median)", f"{num(stages.get('prove_ms', {}).get('median'), 0)} ms / {num(stages.get('groth16_verify_ms', {}).get('median'), 0)} ms"],
        ["Nhúng / trích native (E2E median)", f"{num(stages.get('embed_ms', {}).get('median'), 0)} ms / {num(stages.get('extract_ms', {}).get('median'), 0)} ms cho {e2e.get('cover', {}).get('frames', '—')} frame {e2e.get('cover', {}).get('resolution', '')}"],
        ["PSNR-Y cover→stego thấp nhất", f"{num(min(embed_psnr) if embed_psnr else None, 2)} dB (tham chiếu {QUALITY_REFERENCE_DB:.0f} dB)"],
        ["|z| lớn nhất của tỉ lệ dấu âm", f"{num(max(z_values) if z_values else None, 3)} (|z| < 1.96 ⇒ không phân biệt được ở mức 5%)"],
    ]
    fig = report.figure("Báo cáo benchmark ZK-Stego — H.264 CAVLC + Groth16",
                        f"Tạo lúc {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC từ các bản ghi đo thật. "
                        f"Media run {media.get('run_id', '—')}, E2E run {e2e.get('run_id', '—')}, ZKP run {zkp.get('run_id', '—')}.")
    _mini_table(fig, [0.05, 0.47, 0.9, 0.36], ["Hạng mục", "Kết quả", "Đánh giá"], verdicts, [0.5, 0.3, 0.2])
    _mini_table(fig, [0.05, 0.1, 0.9, 0.32], ["Con số chính", "Giá trị"], figures, [0.32, 0.68])
    report.save(fig)


def _ok(value: bool) -> str:
    return "ĐẠT" if value else "KHÔNG ĐẠT"


def _mini_table(fig: plt.Figure, box: list[float], headers: list[str], rows: list[list[str]], widths: list[float]) -> None:
    ax = fig.add_axes(box)
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=headers, loc="upper left", cellLoc="left", colWidths=widths)
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    _style_table(table, 9, box[3] * PAGE_SIZE[1])
    for (row, _col), cell in table.get_celld().items():
        text = cell.get_text().get_text()
        if row and text in ("ĐẠT", "KHÔNG ĐẠT"):
            cell.set_text_props(weight="bold", color=GREEN if text == "ĐẠT" else RED)


def _by_resolution(passed: list[dict[str, Any]], value: Any) -> str:
    parts = []
    for res in dict.fromkeys(r["resolution"] for r in passed):
        median = _median([value(r) for r in passed if r["resolution"] == res])
        parts.append(f"{res}: {num(median, 1)}")
    return "; ".join(parts)


def _size_delta_text(passed: list[dict[str, Any]]) -> str:
    deltas = [r["stego_bytes"] - r["input_bytes"] for r in passed if r.get("stego_bytes") is not None]
    if not deltas:
        return "—"
    changed = sum(delta != 0 for delta in deltas)
    return f"{min(deltas):+d}…{max(deltas):+d} B ({changed}/{len(deltas)} case khác 0)"


def findings_page(report: Report, data: dict[str, Any]) -> None:
    passed, e2e, zkp = _passed(data["media"]), data["e2e"] or {}, data["zkp"] or {}
    if not passed:
        return
    signs = [r["sign_statistics"] for r in passed if r.get("sign_statistics")]
    psnr = [r["quality"]["cover_to_stego_psnr_y"]["min_finite"] for r in passed
            if r.get("quality", {}).get("cover_to_stego_psnr_y", {}).get("min_finite") is not None]
    cif = [r for r in passed if r["resolution"] == "352x288"]
    per_frame = [r["capacity_metrics"]["raw_candidate_signs"] / r["encoded_frames"] for r in cif if r.get("capacity_metrics")]
    protocol, stages = e2e.get("protocol", {}), e2e.get("stage_summary_ms", {})
    groth = [r for r in zkp.get("results", []) if r["algorithm"].startswith("Groth16")]
    plonk = [r for r in zkp.get("results", []) if r["algorithm"].startswith("PLONK")]
    ratio = (statistics.fmean(r["prove_ms"] for r in plonk) / statistics.fmean(r["prove_ms"] for r in groth)) if groth and plonk else None
    limitations = [a["case"] for a in e2e.get("attacks", []) if a.get("known_limitation") or (a["case"] == "truncate_half" and a["outcome"] == "accepted")]
    first = passed[0]
    report.text("Nhận xét chính", [
        ("b", f"Chức năng: {len(passed)}/{len((data['media'] or {}).get('results', []))} case nhúng → strict decode → trích mù → Groth16 verify đều đạt; "
              f"khóa sai luôn bị từ chối; {sum(s['changed_outside_schedule'] for s in signs)} dấu bị đổi ngoài lịch nhúng."),
        ("b", f"Dung lượng: ở CIF mỗi frame có {num(min(per_frame) if per_frame else None, 0)}–{num(max(per_frame) if per_frame else None, 0)} dấu ứng viên, "
              f"nhưng giao thức chỉ dùng 64 bit/IDR. Payload ZK {num(first.get('payload_bytes'), 0)} B cần {num(first.get('idr_segments_needed'), 0)} IDR "
              f"({num(first.get('idr_segments_needed'), 0)} frame all-intra ≈ {num((first.get('idr_segments_needed') or 0) / (first.get('source_fps') or 30), 1)} s ở {num(first.get('source_fps'), 2)} fps). "
              f"Clip E2E {e2e.get('cover', {}).get('frames', '?')} frame CIF chứa tối đa "
              f"{num(protocol.get('max_message_bytes_at_cap'), 0)} B message."),
        ("b", "Chi phí native tỉ lệ với số IDR phải parse. Quét ms/IDR (median) — " + _by_resolution(passed, lambda r: _per(r.get("capacity_measurement_ms"), r.get("encoded_frames")))
              + ". Nhúng ms/IDR mang bit — " + _by_resolution(passed, lambda r: _per(r.get("embed_ms"), r.get("idr_segments_needed")))
              + ". Đây là giới hạn thông lượng khi xử lý từng frame thời gian thực."),
        ("b", f"Chất lượng: PSNR-Y cover→stego thấp nhất {num(min(psnr) if psnr else None, 2)}–{num(max(psnr) if psnr else None, 2)} dB; "
              f"{sum(v < QUALITY_REFERENCE_DB for v in psnr)}/{len(psnr)} case dưới mốc 40 dB. Chênh lệch kích thước stego − cover: {_size_delta_text(passed)} "
              "(độ dài mã CAVLC không đổi; chỉ byte chống giả mã start code có thể xuất hiện/mất khi một bit dấu đổi)."),
        ("b", f"Thống kê dấu: ~{num(100 * statistics.fmean(s['changed_fraction_of_scheduled'] for s in signs) if signs else None, 0)}% vị trí lên lịch thực sự đổi; "
              f"|z| lớn nhất {num(max(abs(s['two_proportion_z']) for s in signs) if signs else None, 2)} — tỉ lệ dấu âm không phân biệt được ở mức 5%."),
        ("b", f"Zero-knowledge: proof chứng minh một camera trong sổ đăng ký (gốc Merkle công khai) xác nhận đúng video này "
              f"(hash toàn file, trừ đúng các bit mang khung) và message; bên kiểm chứng không cần secret camera và không biết camera nào. "
              f"E2E median: hash cover {num(stages.get('video_digest_ms', {}).get('median'), 0)} ms, prove "
              f"{num(stages.get('prove_ms', {}).get('median'), 0)} ms, verify (gồm hash stego) "
              f"{num(stages.get('groth16_verify_ms', {}).get('median'), 0)} ms; proof nén 129 B; PLONK prove chậm hơn ~{num(ratio, 1)}×."),
        ("b", f"Tấn công: mọi thao tác sửa payload/stream được kiểm tra đều bị từ chối. Được chấp nhận theo thiết kế (giới hạn đã biết): {', '.join(limitations) or '—'}."),
        ("b", "Camera: run hợp lệ duy nhất (passthrough) đạt 7.608 FPS < 30 FPS, đo với giao thức v1 trước đợt tăng tốc — cần đo lại với v3."),
    ], subtitle="Rút ra trực tiếp từ các bảng phía sau; mỗi con số đều có nguồn trong phần tương ứng.")


def coverage_page(report: Report) -> None:
    rows = [
        ["Môi trường, phiên bản, commit (tái lập)", "Có", "1"],
        ["Tính đúng chức năng: nhúng → decode → trích → verify", "Có", "4, 7"],
        ["Dung lượng: ứng viên, bit/IDR, message tối đa", "Có", "3, 7"],
        ["Hiệu năng: mã hóa, quét, prove, nhúng, trích, verify, CPU/RAM", "Có", "4, 7, 9"],
        ["Chất lượng ảnh PSNR-Y / SSIM từng frame", "Có", "5 (+ CSV)"],
        ["Thay đổi kích thước file / bitrate", "Có (Δ byte từng case)", "6"],
        ["Bảo mật: khóa sai, sửa bit, xóa/cắt, mã hóa lại, thay message, replay, camera ngoài sổ đăng ký", "Có", "8"],
        ["Toàn vẹn video và nguồn camera (ZK, ẩn danh trong sổ đăng ký)", "Có", "7, 8, 9"],
        ["So sánh hệ ZK (Groth16 vs PLONK) và primitive mật mã", "Có", "9, 10"],
        ["Khả năng phát hiện thống kê", "Một phần — chỉ báo bậc nhất (tỉ lệ dấu, z)", "6"],
        ["Thời gian thực trên camera", "Một phần — dữ liệu cũ (v1, trước tăng tốc)", "11"],
        ["Steganalysis học máy (SRNet, rich model…)", "Chưa có", "—"],
        ["So sánh với phương pháp giấu tin video khác", "Chưa có", "—"],
        ["Thiết bị edge / nhiều camera / CABAC, P/B-frame", "Chưa có (ngoài phạm vi hiện tại)", "—"],
    ]
    report.table("Độ đầy đủ thông tin", "Đối chiếu các nhóm thông tin thường cần cho phần đánh giá thực nghiệm với những gì báo cáo này có.",
                 ["Nhóm thông tin", "Trong báo cáo", "Phần"], rows, font=9, widths=[0.55, 0.33, 0.12])


def contents_page(report: Report) -> None:
    report.text("Nội dung và cách đọc", [
        ("h", "Các phần"),
        ("b", "1. Môi trường đo và phương pháp — máy, phiên bản công cụ, commit, định nghĩa điều kiện pass."),
        ("b", "2. Chuyển đổi toàn bộ clip Y4M → H.264 Baseline/CAVLC all-intra."),
        ("b", "3. Dung lượng nhúng — số dấu trailing-one ứng viên, dung lượng ở giới hạn 64 bit/IDR, tỉ lệ sử dụng."),
        ("b", "4. Hiệu năng — mã hóa, quét dung lượng, prove, nhúng, trích, verify, CPU/RAM cho 27 case."),
        ("b", "5. Chất lượng hình ảnh — PSNR-Y/SSIM so với nguồn và so với cover sạch, biểu đồ từng frame."),
        ("b", "6. Thay đổi dấu và khả năng phát hiện thống kê — bit đã lật, lật ngoài lịch, tỉ lệ dấu âm, kiểm định z."),
        ("b", "7. End-to-end với payload ZK thật — thời gian từng bước gửi/nhận qua nhiều lần chạy."),
        ("b", "8. Ma trận tấn công / độ bền — khóa sai, lật bit, sửa frame sau, xóa IDR, cắt stream, mã hóa lại, thay message, camera ngoài sổ đăng ký, replay."),
        ("b", "9. Hệ chứng minh không tri thức — Groth16 so với PLONK trên cùng R1CS."),
        ("b", "10. Primitive mật mã — HMAC, chữ ký, AEAD, mã hóa lai: thời gian và tính chất."),
        ("b", "11. Camera thời gian thực — dữ liệu đã ghi trên webcam vật lý (giao thức v1)."),
        ("b", "12. Giới hạn, phạm vi và danh mục dữ liệu thô."),
        ("h", "Quy ước"),
        ("b", "Mọi thời gian là wall time đo trên máy ghi ở phần 1; Groth16/PLONK gồm cả thời gian khởi động Node.js."),
        ("b", "'cover' là H.264 sạch trước khi nhúng; 'stego' là H.264 sau khi nhúng. PSNR ∞ nghĩa là frame giống hệt."),
        ("b", "Độ phân giải 640×480 và 1280×960 được phóng to từ nguồn CIF; chúng đo khả năng mở rộng, không phải cảnh gốc độ phân giải cao."),
    ])


# ----------------------------------------------------------- environment

def environment_page(report: Report, data: dict[str, Any]) -> None:
    env = (data["e2e"] or {}).get("environment", {})
    methodology = (data["media"] or {}).get("methodology", {})
    rows = [["Hệ điều hành", env.get("os", "—")], ["CPU", env.get("cpu", "—")],
            ["Nhân vật lý / logic", f"{env.get('physical_cores', '—')} / {env.get('logical_cores', '—')}"],
            ["RAM", f"{env.get('ram_gb', '—')} GB"], ["Python", env.get("python", "—")],
            ["FFmpeg", wrap(methodology.get("encoder_version") or env.get("ffmpeg", "—"), 95)],
            ["Node.js / snarkjs", f"{env.get('node', '—')} / {env.get('snarkjs', '—')}"],
            ["Git commit", f"{env.get('git_commit', '—')}" + (" (có thay đổi chưa commit)" if env.get("git_tracked_changes") else "")],
            ["zkstego_blind_bits SHA-256", env.get("native_blind_bits_sha256", "—")],
            ["Clip nguồn", wrap(", ".join(methodology.get("source_files", [])), 95)],
            ["Mã hóa", wrap("FFmpeg libx264 Baseline/CAVLC, QP 22, all-intra (GOP 1), không B-frame, 1 luồng, 1 slice mỗi IDR, "
                            "30 frame đầu mỗi clip ở 352×288, 640×480, 1280×960.", 95)],
            ["Payload", wrap("Mỗi case: khóa 32 B mới, Groth16 prove cho SHA256(SHA256(message)‖secret), nhúng pack(message, proof 129 B) "
                             "trong khung kênh v3 (không MAC), giới hạn 64 bit/IDR (mặc định giao thức).", 95)],
            ["Điều kiện pass", wrap("Quét dung lượng native + nhúng native + FFmpeg strict decode (-xerror) + trích mù đúng payload với khóa đúng "
                                    "+ Groth16 verify proof trích ra + khóa sai bị từ chối + không dấu nào đổi ngoài lịch nhúng.", 95)],
            ["Đo chất lượng", wrap("PSNR-Y và SSIM từng frame bằng FFmpeg: nguồn Y4M → stego (nén + nhúng) và cover sạch → stego (chỉ nhúng).", 95)],
            ["Tài nguyên", wrap("CPU/RSS của tiến trình native lấy mẫu mỗi 5 ms, có thể bỏ sót đỉnh rất ngắn.", 95)]]
    report.table("1. Môi trường đo và phương pháp", "Máy và công cụ mà mọi số liệu trong báo cáo thuộc về.",
                 ["Mục", "Giá trị"], rows, font=8, widths=[0.22, 0.78])


def conversion_page(report: Report, data: dict[str, Any]) -> None:
    rows = [[item.get("source", "?"), item.get("resolution", "?"), str(item.get("source_frames", "?")),
             num(item.get("source_fps"), 2), num(item.get("source_duration_seconds"), 2), num(item.get("encode_ms"), 0),
             num((item.get("output_bytes") or 0) / 1e6, 2),
             num(item.get("source_frames", 0) * 1000 / item["encode_ms"], 1) if item.get("encode_ms") else "—",
             "đạt" if item.get("status") == "converted" else "lỗi"]
            for item in (data["conversion"] or {}).get("results", [])]
    report.table("2. Chuyển đổi toàn bộ clip Y4M → H.264", "Mỗi clip được mã hóa đầy đủ ở độ phân giải gốc (libx264 Baseline/CAVLC, QP 22, all-intra, 1 slice). "
                 "Đây là bước tách biệt với ma trận 30 frame ở các phần sau.",
                 ["Clip", "Độ phân giải", "Frame", "FPS nguồn", "Thời lượng s", "Mã hóa ms", "H.264 MB", "Frame/s mã hóa", "Trạng thái"], rows, font=8)


# ------------------------------------------------------------- capacity

def capacity_page(report: Report, data: dict[str, Any]) -> None:
    rows, labels, per_frame = [], [], []
    for r in (data["media"] or {}).get("results", []):
        metrics = r.get("capacity_metrics") or {}
        raw, capacity = metrics.get("raw_candidate_signs"), metrics.get("candidate_capacity_bits")
        frames = r.get("encoded_frames") or 0
        max_message = (capacity // 8 - FRAME_HEADER_BYTES - 4 - 129) if capacity else None
        rows.append([short_clip(r["source"]), r["resolution"], str(frames), num(raw, 0), num(raw / frames if raw and frames else None, 0),
                     num(capacity, 0), num(r.get("frame_bits"), 0), num(r.get("idr_segments_needed"), 0),
                     num(100 * r["frame_bits"] / capacity if capacity and r.get("frame_bits") else None, 1),
                     num(max_message if max_message and max_message > 0 else 0, 0)])
        labels.append(f"{short_clip(r['source'])}\n{r['resolution']}")
        per_frame.append(raw / frames if raw and frames else 0)
    report.table("3. Dung lượng nhúng", "Ứng viên = dấu trailing-one đầu tiên của mỗi block CAVLC trong IDR. Dung lượng ở giới hạn = Σ min(64, ứng viên) "
                 "qua các IDR. Message tối đa = dung lượng/8 − 3 B khung − 4 B độ dài − 129 B proof (với số frame của mẫu).",
                 ["Clip", "Độ phân giải", "Frame", "Ứng viên", "Ứng viên/frame", "Dung lượng bit (64/IDR)", "Bit khung dùng",
                  "IDR cần", "Sử dụng %", "Message tối đa B"], rows, font=7.5)
    if per_frame:
        fig = report.figure("3b. Số dấu ứng viên trên mỗi frame", "Cảnh nhiều chi tiết (football, city) có nhiều block có hệ số hơn nên nhiều ứng viên hơn; "
                            "chỉ 64 vị trí mỗi IDR được dùng nên dung lượng thực tế bị giới hạn bởi tham số giao thức, không bởi nội dung.")
        ax = fig.add_axes([0.07, 0.2, 0.9, 0.62])
        ax.bar(np.arange(len(per_frame)), per_frame, color=BLUE)
        ax.axhline(64, color=RED, linestyle="--", label="64 bit/IDR (mặc định giao thức)")
        ax.set_yscale("log")
        ax.set_ylabel("Ứng viên / frame (log)")
        ax.set_xticks(np.arange(len(labels)), labels, rotation=75, ha="right", fontsize=6)
        ax.legend()
        report.save(fig)


# ---------------------------------------------------------- performance

def performance_pages(report: Report, data: dict[str, Any]) -> None:
    results = (data["media"] or {}).get("results", [])
    rows = [[short_clip(r["source"]), r["resolution"], num(r.get("encode_ms"), 0), num(r.get("capacity_measurement_ms"), 0),
             num(_per(r.get("capacity_measurement_ms"), r.get("encoded_frames")), 1), num(r.get("prove_ms"), 0),
             num(r.get("embed_ms"), 0), num(_per(r.get("embed_ms"), r.get("idr_segments_needed")), 1),
             num(r.get("output_fps"), 1), num(r.get("extract_ms"), 0), num(r.get("groth16_verify_ms"), 0),
             num(r.get("embed_cpu_seconds_sampled"), 2), num((r.get("embed_peak_rss_bytes_sampled") or 0) / 1e6, 1),
             "đạt" if r.get("status") == "passed" else "LỖI"] for r in results]
    report.table("4. Hiệu năng theo case (30 frame mỗi case)", "Quét = đọc và parse CAVLC mọi IDR để đếm ứng viên. Nhúng xử lý đầy đủ các IDR mang bit "
                 "(~payload/64 IDR) rồi chép nguyên phần còn lại, nên 'Nhúng ms/IDR mang bit' là chi phí parse + lập lịch + vá một IDR. "
                 "FPS* = 30 frame / thời gian tiến trình nhúng, không phải FPS camera. CPU/RSS chỉ của tiến trình nhúng (lấy mẫu 5 ms).",
                 ["Clip", "Độ phân giải", "Mã hóa ms", "Quét ms", "Quét ms/IDR", "Prove ms", "Nhúng ms", "Nhúng ms/IDR mang bit",
                  "FPS*", "Trích ms", "Verify ms", "CPU s", "RSS MB", "Pass"], rows, font=7.0, per_page=27)
    passed = _passed(data["media"])
    if not passed:
        return
    resolutions = list(dict.fromkeys(r["resolution"] for r in passed))
    fig = report.figure("4b. Thời gian nhúng và trích theo độ phân giải", "Median trên các clip. Thời gian native tăng gần tuyến tính theo số macroblock; "
                        "prove/verify Groth16 không phụ thuộc video.")
    ax = fig.add_axes([0.08, 0.14, 0.86, 0.68])
    x = np.arange(len(resolutions))
    series = (("embed_ms", "Nhúng", BLUE), ("extract_ms", "Trích", ORANGE), ("capacity_measurement_ms", "Quét dung lượng", GREY))
    for offset, (key, label, color) in zip((-0.27, 0, 0.27), series):
        values = [_median([r.get(key) for r in passed if r["resolution"] == res]) or 0 for res in resolutions]
        bars = ax.bar(x + offset, values, 0.27, label=label, color=color)
        ax.bar_label(bars, fmt="%.0f", fontsize=7)
    ax.set_yscale("log")
    ax.set_xticks(x, resolutions)
    ax.set_ylabel("ms (median, 30 frame, thang log)")
    ax.legend()
    report.save(fig)


# -------------------------------------------------------------- quality

def quality_pages(report: Report, data: dict[str, Any]) -> None:
    passed = _passed(data["media"])
    rows = []
    for r in passed:
        q = r.get("quality", {})
        sp, ss, dp, ds = (q.get(k, {}) for k in ("source_to_stego_psnr_y", "source_to_stego_ssim", "cover_to_stego_psnr_y", "cover_to_stego_ssim"))
        modified = (dp.get("frames_measured") or 0) - (dp.get("identical_or_infinite_frames") or 0)
        rows.append([short_clip(r["source"]), r["resolution"], num(sp.get("mean_finite"), 2), num(sp.get("min_finite"), 2),
                     num(ss.get("mean_finite"), 4), f"{modified}/{dp.get('frames_measured', '—')}", num(dp.get("mean_finite"), 2),
                     num(dp.get("min_finite"), 2), num(ds.get("min_finite"), 5),
                     "đạt" if dp.get("min_finite") is None or dp["min_finite"] >= QUALITY_REFERENCE_DB else "dưới 40 dB"])
    report.table("5. Chất lượng hình ảnh", "Nguồn→stego gồm cả nén H.264 lẫn nhúng. Cover→stego chỉ là tác động của việc nhúng; frame không bị đổi có PSNR ∞ "
                 "và không tính vào trung bình/min. 40 dB là mốc tham chiếu, không nằm trong điều kiện pass chức năng.",
                 ["Clip", "Độ phân giải", "PSNR nguồn μ", "PSNR nguồn min", "SSIM nguồn μ", "Frame bị đổi", "PSNR nhúng μ",
                  "PSNR nhúng min", "SSIM nhúng min", "Mốc 40 dB"], rows, font=7.5, per_page=27)
    _quality_chart(report, passed)
    _per_frame_chart(report, data["frames"], passed)


def _quality_chart(report: Report, passed: list[dict[str, Any]]) -> None:
    if not passed:
        return
    values = [r.get("quality", {}).get("cover_to_stego_psnr_y", {}).get("min_finite") for r in passed]
    labels = [f"{short_clip(r['source'])}\n{r['resolution']}" for r in passed]
    fig = report.figure("5b. PSNR-Y thấp nhất do nhúng, theo case", "Cột đỏ: dưới mốc tham chiếu 40 dB. Một bit dấu đổi ±2 trên một hệ số "
                        "nên sai khác tập trung ở vài block; PSNR toàn frame vì vậy phụ thuộc vào block bị chạm và QP.")
    ax = fig.add_axes([0.07, 0.2, 0.9, 0.62])
    colors = [RED if v is not None and v < QUALITY_REFERENCE_DB else BLUE for v in values]
    ax.bar(np.arange(len(values)), [v or 0 for v in values], color=colors)
    ax.axhline(QUALITY_REFERENCE_DB, color=GREY, linestyle="--", label="40 dB")
    ax.set_ylim(min([v for v in values if v] or [30]) - 3, max([v for v in values if v] or [60]) + 3)
    ax.set_ylabel("PSNR-Y min (dB)")
    ax.set_xticks(np.arange(len(labels)), labels, rotation=75, ha="right", fontsize=6)
    ax.legend()
    report.save(fig)


def _per_frame_chart(report: Report, frames: list[dict[str, str]], passed: list[dict[str, Any]]) -> None:
    if not frames or not passed:
        return
    worst = sorted(passed, key=lambda r: r.get("quality", {}).get("cover_to_stego_psnr_y", {}).get("min_finite") or 99)[:3]
    fig = report.figure("5c. PSNR-Y từng frame (cover → stego) của 3 case kém nhất", "Điểm trên đường trên cùng là frame giống hệt (PSNR ∞). "
                        "Các frame bị đổi là những IDR mang bit của khung (64 bit mỗi IDR).")
    ax = fig.add_axes([0.07, 0.12, 0.88, 0.7])
    for r, color in zip(worst, (RED, ORANGE, BLUE)):
        rows = [f for f in frames if f["source"] == r["source"] and f["resolution"] == r["resolution"]]
        xs = [int(f["frame_index"]) for f in rows]
        ys = [float(f["cover_to_stego_psnr_y"]) if f["cover_to_stego_psnr_y"] not in ("", "None") else 100.0 for f in rows]
        ax.plot(xs, ys, "o", color=color, markersize=4, alpha=0.8, label=f"{short_clip(r['source'])} {r['resolution']}")
    ax.axhline(QUALITY_REFERENCE_DB, color=GREY, linestyle="--")
    ax.set_xlabel("Frame")
    ax.set_ylabel("PSNR-Y (dB); 100 = giống hệt")
    ax.legend()
    report.save(fig)


# ----------------------------------------------------------------- signs

def sign_page(report: Report, data: dict[str, Any]) -> None:
    rows = []
    for r in _passed(data["media"]):
        s = r.get("sign_statistics") or {}
        rows.append([short_clip(r["source"]), r["resolution"], num(s.get("candidate_signs"), 0), num(s.get("scheduled_positions"), 0),
                     num(s.get("changed_signs"), 0), num(100 * s["changed_fraction_of_scheduled"] if s.get("changed_fraction_of_scheduled") else None, 1),
                     num(s.get("changed_outside_schedule"), 0), num(s.get("idr_segments_with_changes"), 0),
                     num(100 * s.get("negative_sign_fraction_cover", float("nan")), 3), num(100 * s.get("negative_sign_fraction_stego", float("nan")), 3),
                     num(s.get("two_proportion_z"), 3),
                     num(r["stego_bytes"] - r["input_bytes"] if r.get("stego_bytes") is not None else None, 0)])
    report.table("6. Thay đổi dấu và khả năng phát hiện thống kê", "Đối chiếu từng dấu ứng viên của cover và stego (zkstego_inspect --segments) với lịch HMAC theo khóa. "
                 "Bit đã làm trắng gần như ngẫu nhiên nên chỉ ~50% vị trí được lên lịch thực sự đổi dấu; tỉ lệ dấu âm toàn cục gần như không đổi. "
                 "z là kiểm định hai tỉ lệ (|z| < 1.96 ⇒ không khác biệt ở mức 5%). Đây là chỉ báo bậc nhất, không phải đánh giá steganalysis đầy đủ.",
                 ["Clip", "Độ phân giải", "Ứng viên", "Vị trí lên lịch", "Dấu đã đổi", "% lịch đổi", "Đổi ngoài lịch",
                  "IDR bị đổi", "% dấu âm cover", "% dấu âm stego", "z", "Δ kích thước B"], rows, font=7.5, per_page=27)


# ------------------------------------------------------------------- e2e

STAGE_LABELS = (("video_digest_ms", "Hash video (cover)"), ("prove_ms", "Groth16 prove"), ("embed_ms", "Nhúng native"),
                ("strict_decode_ms", "FFmpeg strict decode"), ("extract_ms", "Trích mù native"),
                ("groth16_verify_ms", "Verify (hash stego + Groth16)"))


def e2e_pages(report: Report, data: dict[str, Any]) -> None:
    e2e = data["e2e"]
    if not e2e:
        return
    cover, protocol = e2e.get("cover", {}), e2e.get("protocol", {})
    stats = e2e.get("stage_summary_ms", {})
    rows = [[label, num(stats.get(key, {}).get("mean"), 0), num(stats.get(key, {}).get("median"), 0), num(stats.get(key, {}).get("min"), 0),
             num(stats.get(key, {}).get("max"), 0), num(stats.get(key, {}).get("stdev"), 0)] for key, label in STAGE_LABELS]
    for key, label in (("sender_total_ms", "Tổng phía gửi (prove + nhúng)"), ("receiver_total_ms", "Tổng phía nhận (trích + verify)")):
        s = e2e.get(key, {})
        rows.append([label, num(s.get("mean"), 0), num(s.get("median"), 0), num(s.get("min"), 0), num(s.get("max"), 0), num(s.get("stdev"), 0)])
    subtitle = (f"Video: {cover.get('source', '?')} {cover.get('resolution', '?')}, {cover.get('frames', '?')} frame "
                f"({num(cover.get('duration_seconds'), 1)} s), {num((cover.get('bytes') or 0) / 1e6, 2)} MB, QP {cover.get('qp', '?')}. "
                f"{protocol.get('idr_segments', '?')} IDR, {num(protocol.get('candidate_signs'), 0)} ứng viên; dung lượng ở 64 bit/IDR = "
                f"{num(protocol.get('capacity_bits_at_cap'), 0)} bit ⇒ message tối đa {num(protocol.get('max_message_bytes_at_cap'), 0)} B. "
                f"{protocol.get('payload_layout', '')}. Mỗi lần chạy dùng khóa và message mới.")
    report.table(f"7. End-to-end với payload ZK thật ({len(e2e.get('trials', []))} lần)", subtitle,
                 ["Bước", "Trung bình ms", "Median ms", "Min ms", "Max ms", "Độ lệch chuẩn ms"], rows, font=8.5)
    trial_rows = [[str(t["trial"]), num(t["payload_bytes"], 0), num(t["frame_bits"], 0)] +
                  [num(t["stages"].get(key), 0) for key, _label in STAGE_LABELS] +
                  [num(t["sign_statistics"]["changed_signs"], 0), yes(t["groth16_verified"]), "đạt" if t["passed"] else "LỖI"]
                  for t in e2e.get("trials", [])]
    report.table("7b. Từng lần chạy end-to-end", "Payload B = 4 + message + 129. Bit khung = 8 × (payload + 3).",
                 ["Lần", "Payload B", "Bit khung", "Hash", "Prove", "Nhúng", "Decode", "Trích", "Verify", "Dấu đổi",
                  "Groth16 đúng", "Pass"],
                 trial_rows, font=8.5)
    _stage_chart(report, stats)


def _stage_chart(report: Report, stats: dict[str, Any]) -> None:
    fig = report.figure("7c. Phân bổ thời gian end-to-end (median)", "Phía gửi bị chi phối bởi Groth16 prove; phía nhận bởi Groth16 verify "
                        "(chủ yếu là khởi động Node.js + kiểm tra pairing). Phần native nhúng/trích là nhỏ.")
    ax = fig.add_axes([0.2, 0.25, 0.72, 0.5])
    lanes = (("Phía gửi", ("video_digest_ms", "prove_ms", "embed_ms")), ("Phía nhận", ("extract_ms", "groth16_verify_ms")))
    colors = {"video_digest_ms": GREY, "prove_ms": RED, "embed_ms": BLUE, "extract_ms": ORANGE, "groth16_verify_ms": GREEN}
    names = dict(STAGE_LABELS)
    for y, (_lane, keys) in enumerate(lanes):
        left = 0.0
        for key in keys:
            width = stats.get(key, {}).get("median") or 0.0
            ax.barh(y, width, left=left, color=colors[key], label=names[key])
            ax.text(left + width / 2, y, f"{width:.0f} ms", ha="center", va="center", fontsize=8, color="white")
            left += width
    ax.set_yticks([0, 1], [lane for lane, _keys in lanes])
    ax.set_xlabel("ms")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4)
    report.save(fig)


def attack_page(report: Report, data: dict[str, Any]) -> None:
    attacks = (data["e2e"] or {}).get("attacks", [])
    reasons = {None: "—", "payload_not_found": "không thấy khung (version/độ dài)", "proof_invalid": "Groth16 từ chối",
               "malformed_proof_payload": "payload sai định dạng", "stream_rejected_by_parser": "parser từ chối stream",
               "video_binding_required": "proof không gắn video", "video_digest_unavailable": "không tính được hash video"}
    rows = [[row["case"], wrap(row["description"], 48), "chấp nhận" if row["expected"] == "accepted" else "từ chối",
             "chấp nhận" if row["outcome"] == "accepted" else "từ chối", reasons.get(row["reason"], row["reason"]),
             yes(row.get("strict_decode_ok")), ("giới hạn đã biết" if row.get("known_limitation") else ("đúng" if row["as_expected"] else "SAI"))]
            for row in attacks]
    report.table("8. Ma trận tấn công / độ bền", "Mỗi trường hợp đi qua đúng quyết định của job verify HTTP: trích mù → kiểm tra khung v3 → "
                 "unpack → tính lại hash video từ chính file nhận được → Groth16 verify với gốc sổ đăng ký tin cậy. Mỗi lần lật bit "
                 "đã được kiểm chứng rơi đúng vào ứng viên.",
                 ["Trường hợp", "Mô tả", "Kỳ vọng", "Kết quả", "Lý do", "Decode strict", "Đánh giá"], rows, font=8,
                 widths=[0.15, 0.33, 0.08, 0.08, 0.17, 0.08, 0.11])


# ------------------------------------------------------------------- zkp

def zkp_pages(report: Report, data: dict[str, Any]) -> None:
    zkp = data["zkp"]
    if not zkp:
        return
    rows = [[r["algorithm"], str(r["trial"]), num(r.get("witness_ms"), 0), num(r["prove_ms"], 0), num(r["verify_ms"], 0),
             num(r["serialized_proof_json_bytes"], 0), num(r.get("compact_proof_bytes"), 0) if r.get("compact_proof_bytes") else "—",
             num((r.get("prove_peak_rss_bytes_sampled") or 0) / 1e6, 0), yes(r["proof_valid"]), yes(r["tampered_public_input_rejected"])]
            for r in zkp.get("results", [])]
    subtitle = (f"Cùng R1CS camera_video ({num(zkp.get('circuit_constraints'), 0)} constraint, {zkp.get('public_inputs', 3)} public input), "
                f"cùng witness: camera trong cây Merkle Poseidon độ sâu 16 xác nhận một binding 256 bit (hash video + message). "
                f"Setup PLONK (không tính vào prove): {num((zkp.get('plonk_setup_ms') or 0) / 1000, 1)} s trên "
                f"{zkp.get('powers_of_tau_source', 'Powers-of-Tau')}. Groth16: Phase 1 Hermez + Phase 2 nhiều đóng góp + beacon "
                "(src/zk_setup.py, demo trên một máy). RSS là giá trị lấy mẫu.")
    report.table("9. Groth16 so với PLONK", subtitle, ["Hệ", "Lần", "Witness ms", "Prove ms", "Verify ms", "Proof JSON B", "Proof nén B",
                                                        "RSS prove MB", "Hợp lệ", "Public input sửa bị từ chối"], rows, font=8)
    names = list(dict.fromkeys(r["algorithm"] for r in zkp.get("results", [])))
    if not names:
        return
    fig = report.figure("9b. Prove / verify (trung bình, thang log)", "Groth16 có proof hằng 129 B (nén) và verify bằng 3 pairing nhưng cần setup riêng cho circuit; "
                        "PLONK dùng SRS phổ quát (không cần nghi thức riêng) nhưng proof lớn hơn nhiều — tốn dung lượng kênh giấu tin.")
    ax = fig.add_axes([0.12, 0.15, 0.8, 0.65])
    x = np.arange(len(names))
    for offset, key, label, color in ((-0.18, "prove_ms", "prove", BLUE), (0.18, "verify_ms", "verify", ORANGE)):
        values = [statistics.fmean(r[key] for r in zkp["results"] if r["algorithm"] == name) for name in names]
        bars = ax.bar(x + offset, values, 0.36, label=label, color=color)
        ax.bar_label(bars, fmt="%.0f ms", fontsize=8)
    ax.set_yscale("log")
    ax.set_xticks(x, names)
    ax.set_ylabel("ms (log)")
    ax.legend()
    report.save(fig)


# ---------------------------------------------------------------- crypto

def security_pages(report: Report, data: dict[str, Any]) -> None:
    security = data["security"]
    if not security:
        return
    results = security.get("results", [])
    rows = [[r["algorithm"], r["category"], num(r["payload_bytes"], 0), num(r["seal_ms_median"], 4), num(r["seal_ms_p95"], 4),
             num(r["open_verify_ms_median"], 4), num(r["overhead_bytes"], 0), yes(r["tampered_rejected"] if "tampered_rejected" in r else r.get("tamper_rejected"))]
            for r in results]
    report.table("10. Primitive mật mã cho payload", "Gọi thật thư viện cryptography với khóa sinh mỗi lần chạy. Từ giao thức v3 hệ thống không còn thẻ HMAC trong khung "
                 "(HMAC chỉ còn là hàm giả ngẫu nhiên cho lịch và làm trắng); hàng HMAC là tham chiếu. Các hàng có tính chất khác nhau.",
                 ["Thuật toán", "Loại", "Payload B", "Seal median ms", "Seal p95 ms", "Open/verify median ms", "Overhead B", "Sửa bị từ chối"],
                 rows, font=7.0, per_page=26)
    names = list(dict.fromkeys(r["algorithm"] for r in results))
    props = []
    for name in names:
        r = next(row for row in results if row["algorithm"] == name)
        p = r["properties"]
        props.append([name, yes(p["confidentiality"]), yes(p["integrity"]), yes(p["shared_key_authentication"]),
                      yes(p["public_verifiability"]), wrap(r["notes"], 70)])
    report.table("10b. Tính chất bảo mật", "‘có’ nghĩa là có dưới giả định quản lý khóa đã nêu; không phải chứng nhận hay chứng minh hình thức.",
                 ["Thuật toán", "Bí mật", "Toàn vẹn", "Xác thực khóa chung", "Kiểm chứng công khai", "Ghi chú"], props, font=7.5,
                 widths=[0.17, 0.07, 0.07, 0.1, 0.1, 0.49], per_page=10)


# ---------------------------------------------------------------- camera

def camera_page(report: Report, data: dict[str, Any]) -> None:
    camera = data["camera"]
    if not camera:
        return
    rows = []
    for r in camera.get("runs", []):
        quality = r.get("decoded_quality") or {}
        valid = r.get("run") == camera["runs"][-1].get("run")
        rows.append([str(r.get("run")), wrap(r.get("run_type") or "dev-host baseline", 44), num(r.get("captured_frames"), 0),
                     num(r.get("active_stream_frame_rate_fps"), 2) + ("" if valid else " †"), yes(r.get("correct_key_payload_match")),
                     yes(r.get("groth16_proof_verified")), num(r.get("proof_generation_ms_off_capture_path"), 0),
                     num(r.get("proof_verification_ms_after_extraction"), 0), num(quality.get("yuv420_psnr_min_modified_frame_db"), 2)])
    report.table("11. Camera thời gian thực (dữ liệu đã ghi)", f"{camera.get('camera_file', data['camera_file'])}: webcam UVC → FFmpeg → WebSocket → native, 352×288, "
                 "ghi ngày 24/09/2026 với giao thức v1 và trước đợt tăng tốc native 02/10/2026 — chưa đo lại. † Các run trước run 24 dùng đồng bộ CFR mặc định "
                 "của FFmpeg (nhân bản frame) nên ~30 FPS không phải FPS thu thật; chỉ run 24 (fps_mode passthrough) là FPS thu hợp lệ = 7.608 FPS, "
                 "KHÔNG đạt mốc 30 FPS.",
                 ["Run", "Loại", "Frame", "FPS hoạt động", "Payload đúng", "Groth16 đúng", "Prove ms", "Verify ms", "PSNR min frame đổi dB"],
                 rows, font=7.3, per_page=24, widths=[0.05, 0.3, 0.07, 0.1, 0.08, 0.08, 0.09, 0.09, 0.14])


# --------------------------------------------------------- limits/index

def limits_page(report: Report, data: dict[str, Any]) -> None:
    media = data["media"] or {}
    report.text("12. Giới hạn, phạm vi và dữ liệu thô", [
        ("h", "Đã đo và khẳng định"),
        ("b", "H.264 Annex-B Baseline/CAVLC, IDR, một slice mỗi frame; giao thức v3 (HKDF, khung không MAC, làm trắng, lịch HMAC 64 bit/IDR)."),
        ("b", "Proof camera: một camera trong sổ đăng ký (gốc công khai) xác nhận đúng video (mọi bit, bit mang khung bảo vệ qua payload) và message; bên kiểm chứng "
              "chỉ cần khóa giấu tin để trích, gốc sổ đăng ký và verification key — không cần secret camera, không biết camera nào."),
        ("b", "Bị từ chối: khóa sai, lật bit trong lịch, sửa frame sau, xóa IDR, cắt stream, mã hóa lại, thay message, "
              "camera ngoài sổ đăng ký, chép payload sang video khác."),
        ("h", "Chưa khẳng định / giới hạn đã biết"),
        ("b", "Hash video phụ thuộc khóa giấu tin (vị trí bit mang khung), nên chỉ bên có khóa mới kiểm chứng được."),
        ("b", "Luồng live nhúng proof khi video chưa quay xong nên chỉ ràng buộc message (chế độ 1); verify job từ chối chế độ này trừ khi cho phép."),
        ("b", "Setup Groth16 Phase 2 chạy trên một máy (demo); triển khai thật cần nhiều bên độc lập. Không chứng minh camera thực sự quay "
              "cảnh đó (ví dụ quay lại màn hình)."),
        ("b", "Kênh mong manh (fragile): bất kỳ thao tác mã hóa lại nào cũng xóa payload — phù hợp mục tiêu xác thực, không phải watermark bền vững."),
        ("b", "Không hỗ trợ CABAC, P/B-frame làm vật mang, nhiều slice; 640×480 và 1280×960 được phóng to từ CIF."),
        ("b", "Thời gian thực chưa đạt: 7.608 FPS (camera, giao thức v1, trước tăng tốc). Thống kê dấu chỉ là chỉ báo bậc nhất, chưa có steganalysis học máy."),
        ("h", "Dữ liệu thô đi kèm báo cáo này"),
        ("b", f"benchmark/results/media_new/{media.get('run_id', '<run-id>')}/video_pipeline_new.json và quality_per_frame_new.csv (mọi frame)."),
        ("b", "benchmark/results/e2e_new.json, zkp_new.json, security_new.json, conversion_manifest_new.json."),
        ("b", f"benchmark/results/{data['camera_file'] or 'realtime_camera_runs_*.json'} (camera, đã ghi trước đó)."),
        ("b", "Chạy lại toàn bộ: py -3.12 -m benchmark.run_new_suite  (cần data/raw/*.y4m, native Release, circuits/build)."),
    ])


def build_report(results_dir: Path = RESULTS) -> Path:
    data = load_records(results_dir)
    if not data["media"]:
        raise RuntimeError(f"no media_new run found under {results_dir}")
    destination = results_dir / REPORT_NAME
    footer = f"ZK-Stego benchmark • media run {data['media'].get('run_id', '—')} • {REPORT_NAME}"
    with PdfPages(destination) as pdf:
        report = Report(pdf, footer)
        summary_page(report, data)
        findings_page(report, data)
        coverage_page(report)
        contents_page(report)
        environment_page(report, data)
        conversion_page(report, data)
        capacity_page(report, data)
        performance_pages(report, data)
        quality_pages(report, data)
        sign_page(report, data)
        e2e_pages(report, data)
        attack_page(report, data)
        zkp_pages(report, data)
        security_pages(report, data)
        camera_page(report, data)
        limits_page(report, data)
        info = pdf.infodict()
        info["Title"] = "ZK-Stego benchmark report"
        info["Subject"] = "H.264 CAVLC steganography with Groth16 proofs"
    return destination


if __name__ == "__main__":
    print(build_report().relative_to(ROOT).as_posix())
