"""
Section 5 — ZKP System Comparison (corrected artifact: *_new)
===============================================================
Compares a measured Groth16 implementation with literature-only estimates:
  1. Groth16 BN128        — measured baseline; not the current lattice system
  3. PLONK (KZG)          — literature [Gabizon et al., 2019]
  4. STARKs (FRI)         — literature [Ben-Sasson et al., 2018]
  5. Bulletproofs         — literature [Bünz et al., 2018]

An ECDSA P-256 signature is measured separately as a non-ZKP authentication
baseline. It is deliberately excluded from proof-system charts and tables.

Metrics:
  - Proof size (bytes)
  - Proof generation time (ms)
  - Verification time (ms)
  - Trusted setup requirement (boolean)
  - Circuit expressive power

Produces:
  - sec5_zkp_data_new.json
  - sec5_proof_size_new.png  : Proof systems only; hatched = literature estimate
  - sec5_timing_new.png      : Proof systems only; bridge wall time is measured
  - sec5_properties_heatmap_new.png
"""

import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import (
    PALETTE,
    cache_load,
    cache_save,
    save_fig,
    setup_style,
)

CACHE_KEY = "sec5_zkp_data_new"

# -------------------------------------------------------------------------
# ECDSA signature baseline (not zero knowledge)
# -------------------------------------------------------------------------

def _measure_ecdsa_signature(n_trials: int = 20) -> dict:
    """Measure ECDSA signing and verification; this is not a ZKP."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.ec import (
        ECDSA,
        SECP256R1,
        generate_private_key,
    )

    message = b"ZK-Stego benchmark payload - foreman CIF sequence"
    curve   = SECP256R1()

    private_key  = generate_private_key(curve)
    public_key   = private_key.public_key()

    signing_times = []
    verification_times = []
    signature_sizes = []

    for _ in range(n_trials):
        t0  = time.perf_counter()
        sig = private_key.sign(message, ECDSA(hashes.SHA256()))
        signing_times.append((time.perf_counter() - t0) * 1000)
        signature_sizes.append(len(sig))

        t0 = time.perf_counter()
        try:
            public_key.verify(sig, message, ECDSA(hashes.SHA256()))
            ok = True
        except InvalidSignature:
            ok = False
        if not ok:
            raise RuntimeError("ECDSA signature verification failed during benchmark")
        verification_times.append((time.perf_counter() - t0) * 1000)

    return {
        "category": "digital_signature",
        "zero_knowledge": False,
        "algorithm": "ECDSA P-256 with SHA-256",
        "signature_size_bytes_mean": float(np.mean(signature_sizes)),
        "signing_time_ms_mean": float(np.mean(signing_times)),
        "verification_time_ms_mean": float(np.mean(verification_times)),
        "trials": n_trials,
        "simulated": False,
    }


# -------------------------------------------------------------------------
# Groth16: measure actual snarkjs performance
# -------------------------------------------------------------------------
def _measure_groth16(n_trials: int = 3) -> dict:
    """Measure Groth16 prove/verify via actual snarkjs."""
    from benchmark._common import CIRCUITS_DIR
    from src.zk_proof import ZKSnarkBridge, pack

    bridge = ZKSnarkBridge(str(CIRCUITS_DIR))
    secret_key = bytes(range(32))
    message    = b"ZK-bench-v1.0!"  # 14 bytes → 4+14+256 = 274 B blob (matches production)

    prove_times  = []
    verify_times = []
    proof_sizes  = []
    payload_sizes = []

    for i in range(n_trials):
        print(f"    Groth16 trial {i+1}/{n_trials} …")
        t0 = time.perf_counter()
        proof_dict, public_dict = bridge.generate_proof_for_payload(message, secret_key)
        prove_times.append((time.perf_counter() - t0) * 1000)

        # Pack proof to bytes (actual blob size)
        proof_bytes = bridge.proof_to_bytes(proof_dict)
        blob = pack(message, proof_bytes)
        proof_sizes.append(len(proof_bytes))
        payload_sizes.append(len(blob))

        t0 = time.perf_counter()
        valid = bridge.verify(proof_dict, public_dict)
        verify_times.append((time.perf_counter() - t0) * 1000)
        if not valid:
            raise RuntimeError("Groth16 verification failed during benchmark")

    return {
        "proof_size_bytes": int(np.mean(proof_sizes)),
        "proof_bearing_payload_bytes": int(np.mean(payload_sizes)),
        "prove_time_ms":    float(np.mean(prove_times)),
        "verify_time_ms":   float(np.mean(verify_times)),
        "trusted_setup":    True,
        "universal_setup":  False,
        "simulated":        False,
        "trials":           n_trials,
        "measurement_scope": "end-to-end Python bridge wall time, including subprocess overhead",
    }


# -------------------------------------------------------------------------
# Literature values for other ZKP systems
# Illustrative literature estimates, not measurements of executable baselines.
# These values are not guaranteed to represent equivalent statements or setups.
# Sources:
#   PLONK: Gabizon, Williamson, Ciobotaru (2019) — Table 1
#   STARKs: Ben-Sasson et al. (2018) + ZKProof benchmarks 2023
#   Bulletproofs: Bünz et al. (2018) — Table 2 (range proof, 1 value)
# -------------------------------------------------------------------------
LITERATURE_ZKP = {
    "PLONK (KZG)": {
        "proof_size_bytes": 768,
        "prove_time_ms":    85_000,    # ~85 s for similar circuit
        "verify_time_ms":   12.0,
        "trusted_setup":    True,
        "universal_setup":  True,
        "simulated":        True,
        "measurement_method": "literature estimate; not executed by this benchmark",
        "comparable_to_groth16": False,
    },
    "STARKs (FRI)": {
        "proof_size_bytes": 45_000,   # ~45 KB (large due to FRI)
        "prove_time_ms":    200_000,  # ~200 s
        "verify_time_ms":   50.0,
        "trusted_setup":    False,
        "universal_setup":  False,
        "simulated":        True,
        "measurement_method": "literature estimate; not executed by this benchmark",
        "comparable_to_groth16": False,
    },
    "Bulletproofs": {
        "proof_size_bytes": 672,      # 64-bit range proof
        "prove_time_ms":    1_200,    # ~1.2 s
        "verify_time_ms":   900.0,    # ~0.9 s (no pairing -> linear verify)
        "trusted_setup":    False,
        "universal_setup":  False,
        "simulated":        True,
        "measurement_method": "literature estimate; not executed by this benchmark",
        "comparable_to_groth16": False,
    },
}


# -------------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------------
def build_comparison_report(
    proof_systems: dict, signature_baselines: dict
) -> dict:
    """Keep zero-knowledge proof measurements distinct from signatures."""
    return {
        "schema_version": 2,
        "scope": "Groth16 is a measured comparison baseline, not the current lattice system.",
        "proof_systems": proof_systems,
        "signature_baselines": signature_baselines,
    }


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        print("  [cache hit] sec5 — skipping ZKP benchmarks")
        return cached

    proof_systems: dict = {}

    print("  Measuring Groth16 comparison baseline …")
    try:
        proof_systems["Groth16 BN128\n(measured baseline)"] = _measure_groth16(n_trials=3)
    except Exception as e:
        raise RuntimeError(
            "Groth16 measurement failed; refusing to substitute estimated values"
        ) from e

    print("  Measuring ECDSA P-256 signature baseline (not a ZKP) …")
    signature_baselines = {"ECDSA P-256": _measure_ecdsa_signature(n_trials=50)}

    for name, vals in LITERATURE_ZKP.items():
        proof_systems[name] = vals

    report = build_comparison_report(proof_systems, signature_baselines)
    cache_save(CACHE_KEY, report)
    return report


# -------------------------------------------------------------------------
# Plot 1: Proof size comparison
# -------------------------------------------------------------------------
def plot_proof_size(data: dict) -> None:
    setup_style()
    with plt.rc_context({"figure.constrained_layout.use": False}):
        fig, ax = plt.subplots(figsize=(10, 5))

    proof_systems = data["proof_systems"]
    methods = list(proof_systems)
    sizes = [proof_systems[m]["proof_size_bytes"] for m in methods]
    is_sim = [proof_systems[m].get("simulated", True) for m in methods]

    colors_map = {
        "Groth16 BN128\n(measured baseline)": PALETTE["groth16"],
        "PLONK (KZG)":                PALETTE["plonk"],
        "STARKs (FRI)":               PALETTE["stark"],
        "Bulletproofs":               PALETTE["bulletproof"],
    }
    colors = [colors_map.get(m, "#888888") for m in methods]
    hatch  = ["" if not s else "////" for s in is_sim]

    x = np.arange(len(methods))
    bars = ax.bar(x, sizes, color=colors, hatch=hatch,
                  alpha=0.85, width=0.55, zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(methods, fontsize=10)
    ax.set_ylabel("Proof size (bytes)")
    ax.set_title("§5  Proof Size Comparison\n(log scale — smaller = better)")
    ax.set_yscale("log")

    for bar, val, sim in zip(bars, sizes, is_sim):
        label = f"{val:,} B" + (" *" if sim else "")
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() * 1.15,
                label, ha="center", va="bottom", fontsize=9)

    fig.subplots_adjust(bottom=0.22)
    fig.text(
        0.5, 0.015,
        "* Hatched bars are unexecuted literature estimates, not comparable measurements.",
        ha="center", fontsize=8, color="#777777", style="italic",
    )
    save_fig(fig, "sec5_proof_size_new")


# -------------------------------------------------------------------------
# Plot 2: Timing comparison (prove vs verify, log scale)
# -------------------------------------------------------------------------
def plot_timing(data: dict) -> None:
    setup_style()
    with plt.rc_context({"figure.constrained_layout.use": False}):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    proof_systems = data["proof_systems"]
    methods = list(proof_systems)
    prove_ms = [proof_systems[m]["prove_time_ms"] for m in methods]
    verify_ms = [proof_systems[m]["verify_time_ms"] for m in methods]
    is_sim = [proof_systems[m].get("simulated", True) for m in methods]

    colors_map = {
        "Groth16 BN128\n(measured baseline)": PALETTE["groth16"],
        "PLONK (KZG)":                PALETTE["plonk"],
        "STARKs (FRI)":               PALETTE["stark"],
        "Bulletproofs":               PALETTE["bulletproof"],
    }
    colors = [colors_map.get(m, "#888888") for m in methods]
    hatch  = ["" if not s else "////" for s in is_sim]

    x = np.arange(len(methods))
    bar_w = 0.55

    for ax, vals, title, unit_label in [
        (ax1, prove_ms,  "§5A  Proof Generation Time", "Prove time (ms)"),
        (ax2, verify_ms, "§5B  Verification Time",     "Verify time (ms)"),
    ]:
        bars = ax.bar(x, vals, color=colors, hatch=hatch,
                      alpha=0.85, width=bar_w, zorder=3)
        ax.set_xticks(x)
        ax.set_xticklabels(methods, fontsize=9)
        ax.set_ylabel(unit_label)
        ax.set_title(title + "\n(log scale — lower = faster)")
        ax.set_yscale("log")
        for bar, val, sim in zip(bars, vals, is_sim):
            if val >= 1000:
                label = f"{val/1000:.1f} s"
            else:
                label = f"{val:.1f} ms"
            if sim:
                label += " *"
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.15,
                    label, ha="center", va="bottom", fontsize=8.5)

    fig.subplots_adjust(bottom=0.22)
    fig.text(
        0.5, 0.015,
        "* Hatched = literature estimates; Groth16 = end-to-end bridge wall time incl. subprocess overhead.",
        ha="center", fontsize=8, color="#777777", style="italic",
    )
    save_fig(fig, "sec5_timing_new")


# -------------------------------------------------------------------------
# Plot 3: Property heatmap
# -------------------------------------------------------------------------
def plot_properties_heatmap(data: dict) -> None:
    """
    Qualitative property table as a colour-coded heatmap.
    """
    setup_style()

    proof_systems = data["proof_systems"]
    methods = list(proof_systems)
    criteria = [
        "Proof size\n(compact)",
        "Prove speed\n(fast)",
        "Verify speed\n(fast)",
        "No trusted\nsetup",
        "Universal\nsetup",
        "Arbitrary\ncircuits",
        "ZK + embed\nintegration",
    ]

    # Manual illustrative scores only; not measured and not an objective ranking.
    scores_map = {
        "Groth16 BN128\n(measured baseline)": [2, 0, 2, 0, 0, 2, 0],
        "PLONK (KZG)":                        [1, 0, 2, 0, 2, 2, 0],
        "STARKs (FRI)":                       [0, 0, 1, 2, 0, 2, 0],
        "Bulletproofs":                       [1, 1, 1, 2, 0, 1, 0],
    }

    matrix = np.array([scores_map.get(m, [1] * len(criteria)) for m in methods])

    with plt.rc_context({"figure.constrained_layout.use": False}):
        fig, ax = plt.subplots(figsize=(12, 5))
    cmap = plt.get_cmap("RdYlGn")
    im = ax.imshow(matrix.T, cmap=cmap, vmin=0, vmax=2, aspect="auto")

    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels(methods, fontsize=10)
    ax.set_yticks(range(len(criteria)))
    ax.set_yticklabels(criteria, fontsize=10)
    ax.set_title("§5  ZKP Property Comparison (qualitative)\n(green = better)", fontweight="bold")

    cell_labels = {0: "[X] Poor", 1: "~ OK", 2: "[OK] Good"}
    for i, method in enumerate(methods):
        for j, crit in enumerate(criteria):
            val = matrix[i, j]
            text_color = "black" if val == 1 else ("white" if val == 0 else "black")
            ax.text(i, j, cell_labels[val], ha="center", va="center",
                    fontsize=8.5, color=text_color, fontweight="bold" if val == 2 else "normal")

    plt.colorbar(im, ax=ax, ticks=[0, 1, 2],
                 label="Quality (0=poor, 1=ok, 2=good)")

    fig.subplots_adjust(bottom=0.20)
    fig.text(
        0.5, 0.015,
        "Illustrative manual ratings only; criteria are not normalized or independently validated.",
        ha="center", fontsize=8, color="#777777", style="italic",
    )

    save_fig(fig, "sec5_properties_heatmap_new")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------
def run(force: bool = False) -> dict:
    print("\n=== §5  ZKP System Comparison ===")
    data = collect_data(force=force)
    plot_proof_size(data)
    plot_timing(data)
    plot_properties_heatmap(data)
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
