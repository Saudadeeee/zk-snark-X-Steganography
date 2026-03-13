"""
Video Quality Benchmark: Original vs Stego
===========================================
Computes per-frame quality metrics (PSNR, SSIM, MAE, RMSE, mean/std luminance)
between the original H.264 video and the stego H.264 video.

Usage:
    python benchmark/quality_benchmark.py [original.h264] [stego.h264]

Defaults to:
    original : data/encoded/foreman_cif_g8.h264
    stego    : data/output/stego_groth16.h264
"""

import os, sys
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
os.makedirs(RESULTS_DIR, exist_ok=True)

ORIGINAL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "encoded", "foreman_cif_g8.h264")
STEGO    = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "output",  "stego_groth16.h264")
OUT_PNG  = os.path.join(RESULTS_DIR, "quality_comparison.png")
OUT_TXT  = os.path.join(RESULTS_DIR, "quality_results.txt")


def read_frames_ycbcr(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {path}")
    frames = []
    while True:
        ret, bgr = cap.read()
        if not ret:
            break
        frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb))
    cap.release()
    return frames


def clamp_pairs(a_list, b_list):
    n = min(len(a_list), len(b_list))
    if len(a_list) != len(b_list):
        print(f"  [WARN] frame count mismatch: orig={len(a_list)}, stego={len(b_list)} -- using first {n}")
    return a_list[:n], b_list[:n]


print("Loading videos...")
orig_frames  = read_frames_ycbcr(ORIGINAL)
stego_frames = read_frames_ycbcr(STEGO)
orig_frames, stego_frames = clamp_pairs(orig_frames, stego_frames)
N = len(orig_frames)
print(f"  Frames: {N}  resolution: {orig_frames[0].shape[1]}x{orig_frames[0].shape[0]}")

print("Computing per-frame metrics...")

psnr_y = []; psnr_all = []
ssim_y = []; ssim_all = []
mae    = []; rmse     = []
mean_y_orig = []; mean_y_stego = []
std_y_orig  = []; std_y_stego  = []

for oa, sa in zip(orig_frames, stego_frames):
    oy = oa[:, :, 0].astype(np.float64)
    sy = sa[:, :, 0].astype(np.float64)

    psnr_y.append(psnr_fn(oa[:, :, 0], sa[:, :, 0], data_range=255))
    psnr_all.append(psnr_fn(oa, sa, data_range=255))
    ssim_y.append(ssim_fn(oa[:, :, 0], sa[:, :, 0], data_range=255))
    ssim_all.append(float(np.mean([ssim_fn(oa[:, :, c], sa[:, :, c], data_range=255) for c in range(3)])))

    diff = np.abs(oy - sy)
    mae.append(float(diff.mean()))
    rmse.append(float(np.sqrt(np.mean((oy - sy) ** 2))))
    mean_y_orig.append(float(oy.mean()));  mean_y_stego.append(float(sy.mean()))
    std_y_orig.append(float(oy.std()));    std_y_stego.append(float(sy.std()))

frames_x      = list(range(1, N + 1))
psnr_y_plot   = [v if np.isfinite(v) else float("nan") for v in psnr_y]
psnr_all_plot = [v if np.isfinite(v) else float("nan") for v in psnr_all]
finite_psnr   = [v for v in psnr_y if np.isfinite(v)]
inf_count     = sum(1 for v in psnr_y if not np.isfinite(v))

if finite_psnr:
    print(f"  PSNR(Y)  min={min(finite_psnr):.2f}  max={max(finite_psnr):.2f}  mean={np.mean(finite_psnr):.2f} dB  ({inf_count} identical frames)")
else:
    print(f"  PSNR(Y)  all {N} frames identical — no stego modifications detected")
print(f"  SSIM(Y)  min={min(ssim_y):.5f}  max={max(ssim_y):.5f}  mean={np.mean(ssim_y):.5f}")
print(f"  MAE(Y)   min={min(mae):.4f}  max={max(mae):.4f}  mean={np.mean(mae):.4f}")
print(f"  RMSE(Y)  min={min(rmse):.4f}  max={max(rmse):.4f}  mean={np.mean(rmse):.4f}")

# Chart
print("Generating chart...")

COLOR_ORIG = "#2196F3"; COLOR_STEG = "#F44336"; COLOR_DIFF = "#4CAF50"
LW = 1.5; FILL = 0.12

fig = plt.figure(figsize=(16, 18))
fig.patch.set_facecolor("#F8F9FA")
gs = gridspec.GridSpec(4, 2, figure=fig, hspace=0.45, wspace=0.32)
tkw = dict(fontsize=11, fontweight="bold", pad=6)
xkw = dict(fontsize=9); ykw = dict(fontsize=9)
lkw = dict(fontsize=8, loc="best", framealpha=0.8)


def add_panel(ax, x, y1, y2, label1, label2, title, ylabel, c1=COLOR_ORIG, c2=COLOR_STEG):
    ax.plot(x, y1, color=c1, linewidth=LW, label=label1)
    ax.plot(x, y2, color=c2, linewidth=LW, label=label2, linestyle="--")
    ax.fill_between(x, np.array(y1, float), np.array(y2, float), alpha=FILL, color="#9C27B0")
    ax.set_title(title, **tkw); ax.set_xlabel("Frame", **xkw); ax.set_ylabel(ylabel, **ykw)
    ax.legend(**lkw); ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7); ax.set_xlim(1, len(x))


def add_single(ax, x, y, title, ylabel, color=COLOR_DIFF, hline=None, hlabel=None):
    y_arr = np.array(y, float)
    ax.plot(x, y_arr, color=color, linewidth=LW)
    ax.fill_between(x, y_arr, float(np.nanmin(y_arr)), alpha=FILL, color=color)
    if hline is not None:
        ax.axhline(hline, color="#FF9800", linewidth=1, linestyle="--", label=hlabel)
        ax.legend(**lkw)
    ax.set_title(title, **tkw); ax.set_xlabel("Frame", **xkw); ax.set_ylabel(ylabel, **ykw)
    ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.7); ax.set_xlim(1, len(x))


mean_fp = float(np.mean(finite_psnr))
add_single(fig.add_subplot(gs[0, 0]), frames_x, psnr_y_plot,
           f"PSNR (Y channel)  [{inf_count} identical frames = NaN]", "PSNR (dB)",
           hline=mean_fp, hlabel=f"Mean {mean_fp:.2f} dB")

add_panel(fig.add_subplot(gs[0, 1]), frames_x, psnr_y_plot, psnr_all_plot,
          "Y channel", "YCbCr avg", "PSNR — Y vs Full YCbCr", "PSNR (dB)")

add_single(fig.add_subplot(gs[1, 0]), frames_x, ssim_y,
           "SSIM (Y channel)", "SSIM",
           hline=float(np.mean(ssim_y)), hlabel=f"Mean {np.mean(ssim_y):.5f}")

add_panel(fig.add_subplot(gs[1, 1]), frames_x, ssim_y, ssim_all,
          "Y channel", "YCbCr avg", "SSIM — Y vs Full YCbCr", "SSIM")

add_panel(fig.add_subplot(gs[2, 0]), frames_x, mae, rmse,
          "MAE", "RMSE", "MAE & RMSE (Y channel)", "Pixel error")

add_panel(fig.add_subplot(gs[2, 1]), frames_x, mean_y_orig, mean_y_stego,
          "Original", "Stego", "Mean luminance Y", "Mean Y")

add_panel(fig.add_subplot(gs[3, 0]), frames_x, std_y_orig, std_y_stego,
          "Original", "Stego", "Luminance std dev (Y)", "Std Y")

delta_mean = [s - o for s, o in zip(mean_y_stego, mean_y_orig)]
delta_std  = [s - o for s, o in zip(std_y_stego,  std_y_orig)]
ax8 = fig.add_subplot(gs[3, 1])
ax8.plot(frames_x, delta_mean, color=COLOR_ORIG, linewidth=LW, label="Delta mean Y")
ax8.plot(frames_x, delta_std,  color=COLOR_STEG, linewidth=LW, label="Delta std Y", linestyle="--")
ax8.axhline(0, color="gray", linewidth=0.8, linestyle=":")
ax8.set_title("Embedding impact: delta mean & delta std (Y)", **tkw)
ax8.set_xlabel("Frame", **xkw); ax8.set_ylabel("Stego - Original", **ykw)
ax8.legend(**lkw); ax8.grid(True, linestyle=":", linewidth=0.5, alpha=0.7); ax8.set_xlim(1, N)

fig.suptitle(
    f"Video Quality: {os.path.basename(ORIGINAL)}  vs  {os.path.basename(STEGO)}\n"
    f"{N} frames  |  {orig_frames[0].shape[1]}x{orig_frames[0].shape[0]}",
    fontsize=13, fontweight="bold", y=0.995
)
fig.savefig(OUT_PNG, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
plt.close(fig)
print(f"  Chart: {OUT_PNG}")

# Save text summary
with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write(f"Video Quality Results\n{'='*50}\n")
    f.write(f"Original : {ORIGINAL}\n")
    f.write(f"Stego    : {STEGO}\n")
    f.write(f"Frames   : {N}  ({inf_count} identical)\n\n")
    f.write(f"PSNR(Y)  mean={np.mean(finite_psnr):.2f} dB  min={min(finite_psnr):.2f} dB\n")
    f.write(f"SSIM(Y)  mean={np.mean(ssim_y):.6f}  min={min(ssim_y):.6f}\n")
    f.write(f"MAE(Y)   mean={np.mean(mae):.4f}  max={max(mae):.4f}\n")
    f.write(f"RMSE(Y)  mean={np.mean(rmse):.4f}  max={max(rmse):.4f}\n")
    f.write(f"dMean(Y) mean={np.mean(np.abs(delta_mean)):.6f}  max={max(np.abs(delta_mean)):.6f}\n")

print(f"  Stats : {OUT_TXT}")
