"""
System Comparison -- §6: ECDSA Benchmark
==========================================
Compares ECDSA P-256/P-384/P-521 sign/verify timing vs Groth16 prove/verify.

No DICOM dependency. Uses `cryptography` library only.
Reads ZK/results/zk_timing.json if available for Groth16 comparison.

Charts:
  results/ecdsa_benchmark.png   -- 2x2 line + bar charts
  results/ecdsa_benchmark.json  -- raw data

Run:
    cd ImageLevel
    python Benchmark/SystemComparison/ecdsa_benchmark.py
"""

import sys
import time
import json
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from common import save_figure, save_json, results_dir

RDIR = results_dir("SystemComparison")
ZK_TIMING_PATH = BENCH_DIR / "ZK" / "results" / "zk_timing.json"

N_RUNS    = 20
MSG_SIZES = [16, 64, 256, 1024, 4096, 16384]

CURVE_DEFS = [
    ("ECDSA P-256 (128-bit)", 128, "#2196F3"),
    ("ECDSA P-384 (192-bit)", 192, "#4CAF50"),
    ("ECDSA P-521 (256-bit)", 256, "#FF9800"),
]


def _check_cryptography() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa
        return True
    except ImportError:
        print("ERROR: `cryptography` not installed. Run: pip install cryptography")
        return False


def _load_groth16_timing() -> dict:
    """Load measured Groth16 prove/verify times from zk_timing.json if available."""
    if not ZK_TIMING_PATH.exists():
        return {}
    try:
        with open(ZK_TIMING_PATH) as f:
            data = json.load(f)
        prove_mean  = data.get("prove_s",  {}).get("mean")
        verify_mean = data.get("verify_s", {}).get("mean")
        if prove_mean and verify_mean:
            return {
                "prove_ms":  round(prove_mean  * 1000, 2),
                "verify_ms": round(verify_mean * 1000, 2),
                "source": "measured",
            }
    except Exception:
        pass
    return {}


def _benchmark_curve(curve_name: str, security_bits: int, verbose: bool) -> dict:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes

    curve_map = {
        "ECDSA P-256 (128-bit)": ec.SECP256R1(),
        "ECDSA P-384 (192-bit)": ec.SECP384R1(),
        "ECDSA P-521 (256-bit)": ec.SECP521R1(),
    }
    curve = curve_map[curve_name]
    private_key = ec.generate_private_key(curve)
    public_key  = private_key.public_key()

    sign_ms_per_size   = {}
    verify_ms_per_size = {}

    # Warmup: one sign+verify to initialize OpenSSL context before any timing
    _warmup_msg = b"warmup" * 10
    _ws = private_key.sign(_warmup_msg, ec.ECDSA(hashes.SHA256()))
    public_key.verify(_ws, _warmup_msg, ec.ECDSA(hashes.SHA256()))

    for msg_size in MSG_SIZES:
        msg = bytes(range(msg_size % 256)) * (msg_size // 256 + 1)
        msg = msg[:msg_size]

        # Sign timing
        times = []
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            sig = private_key.sign(msg, ec.ECDSA(hashes.SHA256()))
            times.append((time.perf_counter() - t0) * 1000)
        sign_ms_per_size[msg_size] = {
            "mean": round(float(np.mean(times)), 4),
            "std":  round(float(np.std(times)),  4),
            "all":  [round(v, 4) for v in times],
        }

        # Get sig size from last signature
        sig_size = len(sig)

        # Verify timing
        times = []
        for _ in range(N_RUNS):
            t0 = time.perf_counter()
            try:
                public_key.verify(sig, msg, ec.ECDSA(hashes.SHA256()))
            except Exception:
                pass
            times.append((time.perf_counter() - t0) * 1000)
        verify_ms_per_size[msg_size] = {
            "mean": round(float(np.mean(times)), 4),
            "std":  round(float(np.std(times)),  4),
        }

        if verbose:
            print(f"    msg={msg_size:5d}B  sign={sign_ms_per_size[msg_size]['mean']:.3f}ms"
                  f"  verify={verify_ms_per_size[msg_size]['mean']:.3f}ms  sig={sig_size}B")

    # Measure signature size at 256B message (representative)
    msg256 = bytes(range(256))
    actual_sig = private_key.sign(msg256, ec.ECDSA(hashes.SHA256()))
    sig_bytes   = len(actual_sig)

    return {
        "security_bits":     security_bits,
        "sig_size_bytes":    sig_bytes,
        "sign_ms":           sign_ms_per_size,
        "verify_ms":         verify_ms_per_size,
    }


def run(verbose: bool = True) -> dict:
    if not _check_cryptography():
        return {"error": "cryptography_missing"}

    if verbose:
        print(f"ECDSA Benchmark: {N_RUNS} runs per (curve x message_size)\n")

    results = {}
    for curve_name, sec_bits, _ in CURVE_DEFS:
        if verbose:
            print(f"  {curve_name}:")
        results[curve_name] = _benchmark_curve(curve_name, sec_bits, verbose)

    groth16 = _load_groth16_timing()
    if groth16:
        if verbose:
            print(f"\n  Groth16 (from zk_timing.json): prove={groth16['prove_ms']:.1f}ms"
                  f"  verify={groth16['verify_ms']:.2f}ms")
    else:
        if verbose:
            print("\n  Groth16: zk_timing.json not found -- run Benchmark/ZK/zk_timing.py first")

    # ── Figure: 2x2 line charts + bar comparison ──────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    x      = MSG_SIZES
    x_log  = np.array(x)

    # ── Subplot (0,0): Sign time vs message size ───────────────────────────────
    ax = axes[0, 0]
    for curve_name, _, color in CURVE_DEFS:
        d = results[curve_name]
        means = [d["sign_ms"][s]["mean"] for s in MSG_SIZES]
        stds  = [d["sign_ms"][s]["std"]  for s in MSG_SIZES]
        ax.plot(x_log, means, color=color, linewidth=2, marker="o", markersize=6,
                label=curve_name)
        ax.fill_between(x_log,
                        [m - s for m, s in zip(means, stds)],
                        [m + s for m, s in zip(means, stds)],
                        color=color, alpha=0.15)
    ax.set_xscale("log")
    ax.set_xlabel("Message size (bytes, log scale)")
    ax.set_ylabel("Sign time (ms)")
    ax.set_title("ECDSA Sign Time vs Message Size\n(mean +/- std, 20 runs)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    # ── Subplot (0,1): Verify time vs message size ─────────────────────────────
    ax = axes[0, 1]
    for curve_name, _, color in CURVE_DEFS:
        d = results[curve_name]
        means = [d["verify_ms"][s]["mean"] for s in MSG_SIZES]
        stds  = [d["verify_ms"][s]["std"]  for s in MSG_SIZES]
        ax.plot(x_log, means, color=color, linewidth=2, marker="s", markersize=6,
                label=curve_name)
        ax.fill_between(x_log,
                        [m - s for m, s in zip(means, stds)],
                        [m + s for m, s in zip(means, stds)],
                        color=color, alpha=0.15)
    ax.set_xscale("log")
    ax.set_xlabel("Message size (bytes, log scale)")
    ax.set_ylabel("Verify time (ms)")
    ax.set_title("ECDSA Verify Time vs Message Size\n(mean +/- std, 20 runs)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    # ── Subplot (1,0): Signature size vs security level ────────────────────────
    ax = axes[1, 0]
    sec_levels = [results[c]["security_bits"] for c, _, _ in CURVE_DEFS]
    sig_sizes  = [results[c]["sig_size_bytes"] for c, _, _ in CURVE_DEFS]
    ecdsa_colors = [col for _, _, col in CURVE_DEFS]
    bars = ax.plot(sec_levels, sig_sizes, color="#2196F3", linewidth=2.5,
                   marker="o", markersize=10, label="ECDSA (DER encoded)")
    for sl, ss, col in zip(sec_levels, sig_sizes, ecdsa_colors):
        ax.annotate(f"{ss}B", (sl, ss), textcoords="offset points",
                    xytext=(8, 6), fontsize=9.5)
    # Reference lines for ZK schemes
    ax.axhline(192, color="#9C27B0", linestyle="--", linewidth=1.5,
               label="Groth16 proof (192B, measured)")
    ax.axhline(400, color="#FF9800", linestyle=":", linewidth=1.5,
               label="PLONK proof (~400B, literature)")
    ax.set_xlabel("Security level (bits)")
    ax.set_ylabel("Signature / proof size (bytes)")
    ax.set_title("Signature Size vs Security Level\n(vs ZK proof sizes for reference)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(sec_levels)
    ax.set_xticklabels(["P-256\n128-bit", "P-384\n192-bit", "P-521\n256-bit"])
    ax.set_ylim(0, max(sig_sizes) * 1.3)

    # ── Subplot (1,1): ECDSA P-256 vs Groth16 operation timing (bar) ──────────
    ax = axes[1, 1]
    p256_sign_ms   = results["ECDSA P-256 (128-bit)"]["sign_ms"][256]["mean"]
    p256_verify_ms = results["ECDSA P-256 (128-bit)"]["verify_ms"][256]["mean"]

    ops    = ["Sign / Prove", "Verify"]
    ecdsa_vals  = [p256_sign_ms,   p256_verify_ms]
    ecdsa_stds  = [
        results["ECDSA P-256 (128-bit)"]["sign_ms"][256]["std"],
        results["ECDSA P-256 (128-bit)"]["verify_ms"][256]["std"],
    ]

    x_bar = np.arange(len(ops))
    width = 0.3

    ax.bar(x_bar - width/2, ecdsa_vals, width, yerr=ecdsa_stds, capsize=5,
           color="#2196F3", alpha=0.85, label="ECDSA P-256", edgecolor="white")

    if groth16:
        groth16_vals = [groth16["prove_ms"], groth16["verify_ms"]]
        ax.bar(x_bar + width/2, groth16_vals, width, capsize=5,
               color="#9C27B0", alpha=0.85, label="Groth16 (measured)", edgecolor="white")
        for i, (v, label) in enumerate(zip(groth16_vals, ops)):
            ax.text(i + width/2, v * 1.05, f"{v:.1f}ms",
                    ha="center", fontsize=8.5, color="#9C27B0")
    else:
        ax.text(0.5, 0.5, "Groth16 not measured\n(run ZK/zk_timing.py with --with-zk)",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="gray", style="italic")

    for i, (v, s) in enumerate(zip(ecdsa_vals, ecdsa_stds)):
        ax.text(i - width/2, v + s + 0.002, f"{v:.3f}ms",
                ha="center", fontsize=8.5, color="#2196F3")

    ax.set_yscale("log")
    ax.set_xticks(x_bar)
    ax.set_xticklabels(ops)
    ax.set_ylabel("Time (ms, log scale)")
    ax.set_title("ECDSA P-256 vs Groth16: Operation Timing\n(log scale -- sign@256B message)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v:.3f}" if v < 1 else f"{v:.1f}"
    ))

    fig.text(
        0.5, 0.01,
        "Note: ECDSA sign/verify use hash-then-sign (SHA-256), so timing is nearly independent"
        " of message size. Groth16 prove time is fixed per circuit size (~18,680 constraints).",
        ha="center", fontsize=8.5, color="gray", style="italic",
    )
    plt.suptitle(
        "ECDSA Signature vs ZK Proof: Performance Comparison",
        fontsize=14, fontweight="bold", y=1.01,
    )
    plt.tight_layout()
    save_figure(fig, RDIR / "ecdsa_benchmark.png")

    output = {
        "msg_sizes_bytes": MSG_SIZES,
        "n_runs":          N_RUNS,
        "curves":          results,
        "groth16_from_zk_timing": groth16 if groth16 else {"source": "unavailable"},
    }
    save_json(output, RDIR / "ecdsa_benchmark.json")

    if verbose:
        print(f"\nSaved: {RDIR / 'ecdsa_benchmark.png'}")

    return output


if __name__ == "__main__":
    run(verbose=True)
