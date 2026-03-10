"""
Multi-Video Quality Benchmark
==============================
For every .y4m file in data/raw/:
  1. Encode to H.264 baseline (300 frames, GOP=8) if not already present
  2. Run the full steganography embed pipeline -> stego H.264
  3. Decode both videos and compute per-frame quality metrics
  4. Plot a combined chart: one row per video, columns = PSNR / SSIM / Mean-Y

Usage:
    python benchmark/multi_quality_benchmark.py
"""

import os, sys
import subprocess
import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from skimage.metrics import structural_similarity as ssim_fn
from skimage.metrics import peak_signal_noise_ratio as psnr_fn

BENCH_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT        = os.path.dirname(BENCH_DIR)
RESULTS_DIR = os.path.join(BENCH_DIR, "results")
RAW_DIR     = os.path.join(ROOT, "data", "raw")
ENC_DIR     = os.path.join(ROOT, "data", "encoded")
OUT_DIR     = os.path.join(ROOT, "data", "output")
OUT_CHART   = os.path.join(RESULTS_DIR, "multi_quality_comparison.png")
OUT_TXT     = os.path.join(RESULTS_DIR, "multi_quality_results.txt")

FRAMES = 300; GOP = 8; QP = 10

sys.path.insert(0, ROOT)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(ENC_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.embedder.embedder       import CAVLCSafetyFilter, PayloadEmbedder
from src.runtest._idr_extract    import extract_all_idr_blocks

PAYLOAD = b"multi_bench_test_payload_" + bytes(range(64))   # 89 bytes, 712 bits


def encode_video(y4m_path: str, out_h264: str):
    if os.path.exists(out_h264) and os.path.getsize(out_h264) > 0:
        print(f"  [skip] already encoded: {os.path.basename(out_h264)}")
        return
    cmd = [
        "ffmpeg", "-y", "-i", y4m_path,
        "-c:v", "libx264", "-profile:v", "baseline", "-coder", "0",
        "-qp", str(QP), "-g", str(GOP), "-frames:v", str(FRAMES),
        out_h264,
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.decode()}")
    print(f"  [encoded] {os.path.basename(out_h264)}")


def embed_stego(orig_h264: str, stego_h264: str) -> bool:
    if os.path.exists(stego_h264) and os.path.getsize(stego_h264) > 0:
        print(f"  [skip] stego already exists: {os.path.basename(stego_h264)}")
        return True

    rec = BitstreamReconstructor()
    try:
        coeffs, fvd, nC_map, nal_len_map, t1_map = extract_all_idr_blocks(orig_h264, rec)
    except Exception as e:
        print(f"  [ERROR] IDR extract: {e}")
        return False

    safe_pos = CAVLCSafetyFilter().get_safe_positions(
        coeffs, skip_dc=True,
        nC_map=nC_map, nal_length_map=nal_len_map, t1_override_map=t1_map
    )
    if len(safe_pos) < len(PAYLOAD) * 8:
        print(f"  [WARN] capacity {len(safe_pos)} < payload {len(PAYLOAD)*8} bits — skipping")
        return False

    modified, _ = PayloadEmbedder().embed_payload(
        coeffs, PAYLOAD,
        nC_map=nC_map, nal_length_map=nal_len_map, t1_override_map=t1_map
    )
    rec.reconstruct_video(orig_h264, modified, stego_h264, frame_verified_data=fvd)
    print(f"  [embedded] {os.path.basename(stego_h264)}")
    return True


def compute_metrics(orig_h264: str, stego_h264: str) -> dict:
    def read_frames(path):
        cap = cv2.VideoCapture(path)
        frames = []
        while True:
            ret, bgr = cap.read()
            if not ret: break
            frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb))
        cap.release()
        return frames

    orig_f  = read_frames(orig_h264)
    stego_f = read_frames(stego_h264)
    n = min(len(orig_f), len(stego_f))

    psnr, ssim, mean_y_orig, mean_y_stego = [], [], [], []
    for oa, sa in zip(orig_f[:n], stego_f[:n]):
        oy, sy = oa[:, :, 0], sa[:, :, 0]
        psnr.append(psnr_fn(oy, sy, data_range=255))
        ssim.append(ssim_fn(oy, sy, data_range=255))
        mean_y_orig.append(float(oy.mean()))
        mean_y_stego.append(float(sy.mean()))

    return {"n": n, "psnr": psnr, "ssim": ssim,
            "mean_y_orig": mean_y_orig, "mean_y_stego": mean_y_stego}


# Main
y4m_files = sorted(os.path.join(RAW_DIR, f) for f in os.listdir(RAW_DIR) if f.endswith(".y4m"))
if not y4m_files:
    print("No .y4m files found in data/raw/")
    sys.exit(1)

print(f"Found {len(y4m_files)} source video(s):")
for p in y4m_files:
    print(f"  {os.path.basename(p)}")

video_results = []

for y4m in y4m_files:
    stem       = os.path.splitext(os.path.basename(y4m))[0]
    orig_h264  = os.path.join(ENC_DIR, f"{stem}_g{GOP}.h264")
    stego_h264 = os.path.join(OUT_DIR,  f"{stem}_stego.h264")

    print(f"\n{'='*55}\n  {stem}\n{'='*55}")
    encode_video(y4m, orig_h264)
    if not embed_stego(orig_h264, stego_h264):
        continue

    print("  Computing quality metrics...")
    m = compute_metrics(orig_h264, stego_h264)
    video_results.append((stem, m))

    fp = [v for v in m["psnr"] if np.isfinite(v)]
    print(f"  Frames : {m['n']}")
    print(f"  PSNR(Y): mean={np.mean(fp):.2f} dB  min={min(fp):.2f} dB")
    print(f"  SSIM(Y): mean={np.mean(m['ssim']):.4f}  min={min(m['ssim']):.4f}")

if not video_results:
    print("No results to plot.")
    sys.exit(1)

# Plot
print("\nGenerating chart...")

N_VIDS = len(video_results)
fig    = plt.figure(figsize=(16, 5 * N_VIDS + 1))
fig.patch.set_facecolor("#F8F9FA")
gs     = gridspec.GridSpec(N_VIDS, 3, figure=fig, hspace=0.55, wspace=0.3)

C_ORIG = "#2196F3"; C_STEG = "#F44336"; C_DIFF = "#4CAF50"; C_DIFF2 = "#FF9800"
LW = 1.5; ALPHA = 0.12


def plot_psnr(ax, x, psnr, title):
    plot   = [v if np.isfinite(v) else float("nan") for v in psnr]
    finite = [v for v in psnr if np.isfinite(v)]
    if not finite:
        ax.text(0.5, 0.5, "all identical", ha="center", transform=ax.transAxes); return
    mn = float(np.mean(finite))
    ax.plot(x, plot, color=C_DIFF, linewidth=LW)
    ax.axhline(mn, color=C_DIFF2, linewidth=1, linestyle="--", label=f"Mean {mn:.2f} dB")
    ax.fill_between(x, plot, float(np.nanmin(plot)), alpha=ALPHA, color=C_DIFF)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_ylabel("PSNR (dB)", fontsize=8); ax.set_xlabel("Frame", fontsize=8)
    ax.legend(fontsize=7); ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7)
    ax.set_xlim(1, len(x)); ax.ticklabel_format(useOffset=False, axis="y")


def plot_ssim(ax, x, ssim, title):
    mn = float(np.mean(ssim))
    ax.plot(x, ssim, color=C_DIFF, linewidth=LW)
    ax.axhline(mn, color=C_DIFF2, linewidth=1, linestyle="--", label=f"Mean {mn:.4f}")
    ax.fill_between(x, ssim, min(ssim), alpha=ALPHA, color=C_DIFF)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_ylabel("SSIM", fontsize=8); ax.set_xlabel("Frame", fontsize=8)
    ax.legend(fontsize=7); ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7); ax.set_xlim(1, len(x))


def plot_mean_y(ax, x, orig, stego, title):
    ax.plot(x, orig,  color=C_ORIG, linewidth=LW, label="Original")
    ax.plot(x, stego, color=C_STEG, linewidth=LW, label="Stego", linestyle="--")
    ax.fill_between(x, np.array(orig), np.array(stego), alpha=ALPHA, color="#9C27B0")
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_ylabel("Mean Y", fontsize=8); ax.set_xlabel("Frame", fontsize=8)
    ax.legend(fontsize=7); ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7); ax.set_xlim(1, len(x))


for row, (stem, m) in enumerate(video_results):
    x = list(range(1, m["n"] + 1))
    plot_psnr(fig.add_subplot(gs[row, 0]), x, m["psnr"],   f"{stem} — PSNR (Y)")
    plot_ssim(fig.add_subplot(gs[row, 1]), x, m["ssim"],   f"{stem} — SSIM (Y)")
    plot_mean_y(fig.add_subplot(gs[row, 2]), x, m["mean_y_orig"], m["mean_y_stego"],
                f"{stem} — Mean luminance Y")

fig.suptitle(
    f"Multi-Video Quality Comparison  ({FRAMES} frames, GOP={GOP}, QP={QP})",
    fontsize=13, fontweight="bold", y=1.005
)
fig.savefig(OUT_CHART, dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.close(fig)
print(f"  Chart  : {OUT_CHART}")

# Summary table + save to txt
lines = ["=" * 65,
         f"  {'Video':<28}  {'PSNR mean':>10}  {'PSNR min':>9}  {'SSIM mean':>10}",
         "  " + "-" * 61]
for stem, m in video_results:
    fp = [v for v in m["psnr"] if np.isfinite(v)]
    lines.append(f"  {stem:<28}  {np.mean(fp):>9.2f}  {min(fp):>9.2f}  {np.mean(m['ssim']):>10.5f}")
lines.append("=" * 65)

print()
for l in lines:
    print(l)

with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write(f"Multi-Video Quality Results\n")
    f.write(f"Frames={FRAMES}  GOP={GOP}  QP={QP}\n\n")
    f.write("\n".join(lines) + "\n")

print(f"\n  Stats  : {OUT_TXT}")
