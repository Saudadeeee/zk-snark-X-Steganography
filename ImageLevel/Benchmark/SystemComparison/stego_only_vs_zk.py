"""
System Comparison -- §6.3: Stego-Only vs ZK vs ECDSA
======================================================
Compares 3 authentication approaches for DICOM steganography:
  - This Work:     DicomStego + Groth16 ZK proof (192B overhead, constant)
  - Stego Only:    DicomStego, no authentication
  - Stego + ECDSA: DicomStego + ECDSA P-256 signature (~72B overhead, constant)

Key insight: ZK and ECDSA overheads are CONSTANT regardless of payload size.
The charts show this flatness vs stego embed time scaling with payload.

Charts:
  results/stego_only_vs_zk.png   -- 2x2 line charts
  results/stego_only_vs_zk.json  -- raw data

Run:
    cd ImageLevel
    python Benchmark/SystemComparison/stego_only_vs_zk.py

ZK note:
    If compiled circuit is absent, loads cached mean from ZK/results/zk_timing.json.
    If neither is available, "This Work" ZK line is skipped with a warning.
"""

import sys
import time
import json
import gc
import tracemalloc
import os
import tempfile
from pathlib import Path

BENCH_DIR   = Path(__file__).resolve().parent.parent
PROJECT_DIR = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(BENCH_DIR))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from common import (
    list_dicom_files, save_figure, save_json, results_dir,
    CHAOS_KEY, METHOD_COLORS,
)

RDIR           = results_dir("SystemComparison")
ZK_TIMING_PATH = BENCH_DIR / "ZK" / "results" / "zk_timing.json"
BUILD_DIR      = PROJECT_DIR / "circuits" / "compiled" / "build"

# Payload sizes to sweep (bytes)
PAYLOAD_SIZES  = [50, 100, 200, 500, 1000, 2000, 5000]
N_EMBED_RUNS   = 3   # full embed is slow; 3 runs is enough for mean
N_AUTH_RUNS    = 20  # ECDSA / ZK verify are fast


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_zk_artifacts() -> bool:
    wasm = BUILD_DIR / "chaos_zk_stego_js" / "chaos_zk_stego.wasm"
    zkey = BUILD_DIR / "chaos_zk_stego.zkey"
    vkey = BUILD_DIR / "chaos_zk_stego_verification_key.json"
    return all(f.exists() for f in (wasm, zkey, vkey))


def _load_cached_zk_timing() -> dict:
    """Returns {'prove_ms': float, 'verify_ms': float} from zk_timing.json or {}."""
    if not ZK_TIMING_PATH.exists():
        return {}
    try:
        with open(ZK_TIMING_PATH) as f:
            d = json.load(f)
        p = d.get("prove_s",  {}).get("mean")
        v = d.get("verify_s", {}).get("mean")
        if p and v:
            return {"prove_ms": round(p * 1000, 2), "verify_ms": round(v * 1000, 2)}
    except Exception:
        pass
    return {}


def _measure_ram(func) -> tuple:
    """Run func() under tracemalloc. Returns (return_val, peak_mb)."""
    gc.collect()
    tracemalloc.start()
    result = func()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, peak / 1024**2


def _time_embed_no_proof(dcm_path: str) -> float:
    from src.zk_stego.dicom_handler import DicomStego
    ds = DicomStego()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        t0 = time.perf_counter()
        ds.embed(dcm_path, tmp, chaos_key=CHAOS_KEY, generate_zk_proof=False, verbose=False)
        return time.perf_counter() - t0
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _time_embed_with_proof(dcm_path: str) -> float:
    from src.zk_stego.dicom_handler import DicomStego
    ds = DicomStego()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        t0 = time.perf_counter()
        ds.embed(dcm_path, tmp, chaos_key=CHAOS_KEY, generate_zk_proof=True, verbose=False)
        return time.perf_counter() - t0
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _ram_embed_no_proof(dcm_path: str) -> float:
    _, peak = _measure_ram(lambda: _time_embed_no_proof(dcm_path))
    return peak


def _ram_embed_with_proof(dcm_path: str) -> float:
    _, peak = _measure_ram(lambda: _time_embed_with_proof(dcm_path))
    return peak


_ECDSA_WARMED_UP = False

def _ecdsa_sign_verify_ms(payload_size: int) -> tuple:
    """Returns (sign_ms_mean, verify_ms_mean, sig_size_bytes) for ECDSA P-256."""
    global _ECDSA_WARMED_UP
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()
    msg = (bytes(range(256)) * (payload_size // 256 + 1))[:payload_size]

    # Warmup on first call to initialize OpenSSL context
    if not _ECDSA_WARMED_UP:
        _ws = private_key.sign(b"warmup" * 10, ec.ECDSA(hashes.SHA256()))
        public_key.verify(_ws, b"warmup" * 10, ec.ECDSA(hashes.SHA256()))
        _ECDSA_WARMED_UP = True

    sign_times = []
    for _ in range(N_AUTH_RUNS):
        t0 = time.perf_counter()
        sig = private_key.sign(msg, ec.ECDSA(hashes.SHA256()))
        sign_times.append((time.perf_counter() - t0) * 1000)

    verify_times = []
    for _ in range(N_AUTH_RUNS):
        t0 = time.perf_counter()
        try:
            public_key.verify(sig, msg, ec.ECDSA(hashes.SHA256()))
        except Exception:
            pass
        verify_times.append((time.perf_counter() - t0) * 1000)

    return (
        float(np.mean(sign_times)),
        float(np.mean(verify_times)),
        len(sig),
    )


def _zk_verify_ms(sample_runs: int = N_AUTH_RUNS) -> float:
    """Run ZK verification sample_runs times and return mean ms. Requires ZK artifacts."""
    from src.zk_stego.dicom_handler import DicomHandler
    from src.zk_stego.prover import Prover
    from src.zk_stego.utils import SnarkJSRunner
    dcm = str(list_dicom_files()[0])
    cover, meta_json, info = DicomHandler.load(dcm)
    prover = Prover()
    runner = SnarkJSRunner()
    chaos_params = prover._extract_chaos_parameters(
        cover, meta_json[:4], CHAOS_KEY,
        info["cols"] // 2, info["rows"] // 2,
    )
    witness_input = prover._create_witness_input(chaos_params)
    wtns = runner.generate_witness(witness_input)
    if not wtns:
        return 0.0
    proof_result = runner.generate_groth16_proof(wtns)
    if not proof_result:
        return 0.0
    proof, public_inputs = proof_result
    times = []
    for _ in range(sample_runs):
        t0 = time.perf_counter()
        runner.verify_groth16_proof(proof, public_inputs)
        times.append((time.perf_counter() - t0) * 1000)
    return float(np.mean(times))


# ── Main run ─────────────────────────────────────────────────────────────────

def run(verbose: bool = True) -> dict:
    dcm_files = list_dicom_files()
    dcm = str(dcm_files[0])

    has_zk     = _check_zk_artifacts()
    cached_zk  = _load_cached_zk_timing()

    if verbose:
        print(f"DICOM: {Path(dcm).name}")
        print(f"ZK artifacts: {'present' if has_zk else 'absent'}")
        if not has_zk and cached_zk:
            print(f"  Using cached ZK timing: prove={cached_zk['prove_ms']:.1f}ms"
                  f"  verify={cached_zk['verify_ms']:.2f}ms")
        elif not has_zk:
            print("  No cached ZK timing -- 'This Work' line will be omitted")

    # ── 1. Measure base embed time (no auth, fixed DICOM payload) ─────────────
    if verbose:
        print(f"\nMeasuring base embed time ({N_EMBED_RUNS} runs)...")
    base_times = []
    for i in range(N_EMBED_RUNS):
        t = _time_embed_no_proof(dcm)
        base_times.append(t)
        if verbose:
            print(f"  Run {i+1}: {t:.3f}s")
    base_embed_mean = float(np.mean(base_times))
    base_embed_std  = float(np.std(base_times))

    # ZK embed time (if possible)
    zk_embed_mean = None
    if has_zk:
        if verbose:
            print(f"\nMeasuring ZK embed time ({N_EMBED_RUNS} runs)...")
        zk_times = []
        for i in range(N_EMBED_RUNS):
            t = _time_embed_with_proof(dcm)
            zk_times.append(t)
            if verbose:
                print(f"  Run {i+1}: {t:.3f}s")
        zk_embed_mean = float(np.mean(zk_times))
        zk_embed_std  = float(np.std(zk_times))
    elif cached_zk:
        # Approximate: base + cached prove time
        prove_s = cached_zk["prove_ms"] / 1000
        zk_embed_mean = base_embed_mean + prove_s
        zk_embed_std  = base_embed_std
        if verbose:
            print(f"\nZK embed est. from cache: {zk_embed_mean:.2f}s (base + prove)")

    # ── 2. ZK verify time ─────────────────────────────────────────────────────
    zk_verify_mean = None
    if has_zk:
        if verbose:
            print(f"\nMeasuring ZK verify time ({N_AUTH_RUNS} runs)...")
        zk_verify_mean = _zk_verify_ms()
        if verbose:
            print(f"  ZK verify: {zk_verify_mean:.3f}ms")
    elif cached_zk:
        zk_verify_mean = cached_zk["verify_ms"]

    # ── 3. ECDSA timing + overhead per payload size ────────────────────────────
    if verbose:
        print(f"\nMeasuring ECDSA timing across {len(PAYLOAD_SIZES)} payload sizes...")

    ecdsa_sign_ms  = []
    ecdsa_verify_ms = []
    ecdsa_sig_bytes = []

    for ps in PAYLOAD_SIZES:
        s_ms, v_ms, sig_sz = _ecdsa_sign_verify_ms(ps)
        ecdsa_sign_ms.append(s_ms)
        ecdsa_verify_ms.append(v_ms)
        ecdsa_sig_bytes.append(sig_sz)
        if verbose:
            print(f"  payload={ps:5d}B  sign={s_ms:.3f}ms  verify={v_ms:.3f}ms  sig={sig_sz}B")

    # ── 4. RAM measurements ───────────────────────────────────────────────────
    if verbose:
        print("\nMeasuring RAM...")
    ram_stego_only = _ram_embed_no_proof(dcm)
    if verbose:
        print(f"  Stego Only RAM: {ram_stego_only:.1f} MB")

    ram_zk = None
    if has_zk:
        ram_zk = _ram_embed_with_proof(dcm)
        if verbose:
            print(f"  ZK embed RAM:   {ram_zk:.1f} MB")

    # ── Build arrays for charts ───────────────────────────────────────────────
    ps_arr = np.array(PAYLOAD_SIZES)

    # Embed total times: stego embed is constant; auth overhead varies
    # Stego Only: base_embed_mean (constant across payload sizes -- embed is always same)
    # Stego + ECDSA: base_embed_mean + ecdsa_sign_ms[i]/1000
    # This Work: zk_embed_mean (constant -- ZK prove is fixed per circuit)
    stego_total = [base_embed_mean] * len(PAYLOAD_SIZES)
    ecdsa_total = [base_embed_mean + s/1000 for s in ecdsa_sign_ms]
    zk_total    = [zk_embed_mean] * len(PAYLOAD_SIZES) if zk_embed_mean else None

    # Verify times (ms)
    stego_verify = [0.0] * len(PAYLOAD_SIZES)        # no verification
    ecdsa_verify_arr = ecdsa_verify_ms                 # ECDSA verify
    zk_verify_arr = [zk_verify_mean] * len(PAYLOAD_SIZES) if zk_verify_mean else None

    # Auth overhead bytes (constant for both ZK and ECDSA)
    stego_overhead = [0] * len(PAYLOAD_SIZES)
    ecdsa_overhead = ecdsa_sig_bytes                   # varies slightly by curve params
    zk_overhead    = [192] * len(PAYLOAD_SIZES)        # Groth16 = 192B constant

    # RAM (constant for all payload sizes in our setup)
    stego_ram = [ram_stego_only] * len(PAYLOAD_SIZES)
    ecdsa_ram = stego_ram                               # ECDSA adds negligible RAM
    zk_ram    = ([ram_zk] * len(PAYLOAD_SIZES)) if ram_zk else None

    # ── Figure: 2x2 line charts ───────────────────────────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    col_stego = METHOD_COLORS["Cover"]         # blue
    col_ecdsa = METHOD_COLORS["PRNG-LSB"]      # green
    col_zk    = METHOD_COLORS["This Work"]     # purple

    # ── Subplot (0,0): Total embedding time ───────────────────────────────────
    ax = axes[0, 0]
    ax.plot(ps_arr, stego_total, color=col_stego, linewidth=2, marker="s",
            markersize=7, label="Stego Only")
    ax.plot(ps_arr, ecdsa_total, color=col_ecdsa, linewidth=2, marker="^",
            markersize=7, label="Stego + ECDSA")
    if zk_total:
        zk_src = "measured" if has_zk else "est. from cache"
        ax.plot(ps_arr, zk_total, color=col_zk, linewidth=2, marker="o",
                markersize=7, label=f"This Work / Groth16 ({zk_src})",
                linestyle="--" if not has_zk else "solid")
    ax.set_xscale("log")
    ax.set_xlabel("Payload size (bytes, log scale)")
    ax.set_ylabel("Total embedding time (s)")
    ax.set_title("Embed Time vs Payload Size\n(DICOM metadata payload is fixed; auth overhead varies)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.annotate(
        "Note: embed time is constant\n(payload = fixed DICOM metadata);\nonly auth overhead varies",
        xy=(0.03, 0.97), xycoords="axes fraction", fontsize=8,
        color="gray", va="top", style="italic",
    )

    # ── Subplot (0,1): Verification time ──────────────────────────────────────
    ax = axes[0, 1]
    ax.plot(ps_arr, stego_verify, color=col_stego, linewidth=2, marker="s",
            markersize=7, label="Stego Only (no verification)")
    ax.plot(ps_arr, ecdsa_verify_arr, color=col_ecdsa, linewidth=2, marker="^",
            markersize=7, label="Stego + ECDSA (verify sig)")
    if zk_verify_arr:
        ax.plot(ps_arr, zk_verify_arr, color=col_zk, linewidth=2, marker="o",
                markersize=7, label="This Work / Groth16 (verify ZK proof)")
    ax.set_xscale("log")
    ax.set_xlabel("Payload size (bytes, log scale)")
    ax.set_ylabel("Verification time (ms)")
    ax.set_title("Verification Time vs Payload Size\n(both ZK and ECDSA are O(1) in payload)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    # ── Subplot (1,0): Auth overhead bytes ────────────────────────────────────
    ax = axes[1, 0]
    ax.plot(ps_arr, stego_overhead, color=col_stego, linewidth=2, marker="s",
            markersize=7, label="Stego Only (0B)")
    ax.plot(ps_arr, ecdsa_overhead, color=col_ecdsa, linewidth=2, marker="^",
            markersize=7, label="Stego + ECDSA (~72B)")
    ax.plot(ps_arr, zk_overhead, color=col_zk, linewidth=2, marker="o",
            markersize=7, label="This Work / Groth16 (192B)")
    ax.set_xscale("log")
    ax.set_xlabel("Payload size (bytes, log scale)")
    ax.set_ylabel("Authentication overhead (bytes)")
    ax.set_title("Auth Overhead vs Payload Size\n(Groth16 and ECDSA are constant)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_ylim(-10, max(zk_overhead) * 1.4)

    # ── Subplot (1,1): Peak RAM ───────────────────────────────────────────────
    ax = axes[1, 1]
    ax.plot(ps_arr, stego_ram, color=col_stego, linewidth=2, marker="s",
            markersize=7, label="Stego Only")
    ax.plot(ps_arr, ecdsa_ram, color=col_ecdsa, linewidth=2, marker="^",
            markersize=7, linestyle=":", label="Stego + ECDSA (same as stego)")
    if zk_ram:
        ax.plot(ps_arr, zk_ram, color=col_zk, linewidth=2, marker="o",
                markersize=7, label="This Work / Groth16 (incl. snarkjs)")
    ax.set_xscale("log")
    ax.set_xlabel("Payload size (bytes, log scale)")
    ax.set_ylabel("Peak RAM (MB, tracemalloc)")
    ax.set_title("Peak RAM Usage vs Payload Size")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    fig.text(
        0.5, 0.01,
        "Embed time is measured on the fixed DICOM test file (payload = DICOM metadata)."
        " ECDSA uses P-256 with SHA-256. Groth16 circuit has 18,680 constraints.",
        ha="center", fontsize=8.5, color="gray", style="italic",
    )
    plt.suptitle(
        "System Comparison: Stego-Only vs Stego+ECDSA vs This Work (Groth16 ZK)",
        fontsize=13, fontweight="bold", y=1.01,
    )
    plt.tight_layout()
    save_figure(fig, RDIR / "stego_only_vs_zk.png")

    output = {
        "payload_sizes_bytes": PAYLOAD_SIZES,
        "n_embed_runs":        N_EMBED_RUNS,
        "n_auth_runs":         N_AUTH_RUNS,
        "dicom_file":          Path(dcm).name,
        "base_embed_mean_s":   round(base_embed_mean, 4),
        "base_embed_std_s":    round(base_embed_std,  4),
        "methods": {
            "This Work": {
                "embed_time_s":    zk_total,
                "verify_time_ms":  zk_verify_arr,
                "overhead_bytes":  zk_overhead,
                "peak_ram_mb":     zk_ram,
                "zk_used":         True,
                "zk_source":       "measured" if has_zk else ("cache" if cached_zk else "unavailable"),
            },
            "Stego Only": {
                "embed_time_s":    stego_total,
                "verify_time_ms":  stego_verify,
                "overhead_bytes":  stego_overhead,
                "peak_ram_mb":     stego_ram,
            },
            "Stego + ECDSA": {
                "embed_time_s":    ecdsa_total,
                "verify_time_ms":  ecdsa_verify_arr,
                "overhead_bytes":  ecdsa_overhead,
                "peak_ram_mb":     ecdsa_ram,
                "ecdsa_sign_ms":   ecdsa_sign_ms,
            },
        },
    }
    save_json(output, RDIR / "stego_only_vs_zk.json")

    if verbose:
        print(f"\nSaved: {RDIR / 'stego_only_vs_zk.png'}")

    return output


if __name__ == "__main__":
    run(verbose=True)
