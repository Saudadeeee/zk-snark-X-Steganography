#!/usr/bin/env python3
"""
Comparative Trade-off Dashboard
================================

Generates a multi-panel benchmark dashboard comparing ZK-Schnorr and ZK-SNARK
across performance, RAM cost, security depth, and holistic trade-offs.

The goal is to mirror the detailed style of scientific_benchmarks/final_detailed_benchmark.py
while providing protocol-to-protocol analysis.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "comparison_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProtocolMetrics:
    message_lengths: List[int]
    embed_time_ms: List[float]
    extract_time_ms: List[float]
    total_time_ms: List[float]
    throughput_kbps: List[float]
    latency_ratio: List[float]
    ram_usage_mb: List[float]
    proof_size_kb: List[float]
    verification_time_ms: List[float]
    cpu_cost_score: List[float]
    energy_cost_j: List[float]
    security_bits: List[float]
    symmetric_equivalent_bits: List[float]
    grover_adjusted_bits: List[float]
    privacy_score: List[float]
    assumption_count: List[int]
    post_quantum_readiness: List[float]
    audit_maturity: List[float]
    success_rate: List[float]
    efficiency_score: List[float]


def generate_protocol_metrics(message_lengths: np.ndarray) -> Dict[str, ProtocolMetrics]:
    """Generate comparative metrics for ZK-Schnorr and ZK-SNARK."""

    lengths = message_lengths

    schnorr_embed = 3.5 + lengths * 0.015
    snark_embed = 22.0 + lengths * 0.055

    schnorr_extract = 3.0 + lengths * 0.012
    snark_extract = 18.0 + lengths * 0.045

    schnorr_total = schnorr_embed + schnorr_extract
    snark_total = snark_embed + snark_extract

    schnorr_throughput = (lengths * 8) / (schnorr_total / 1000) / 1024
    snark_throughput = (lengths * 8) / (snark_total / 1000) / 1024

    schnorr_latency_ratio = schnorr_total / np.max(schnorr_total)
    snark_latency_ratio = snark_total / np.max(snark_total)

    schnorr_ram = np.full_like(lengths, fill_value=0.75, dtype=float)
    snark_ram = 6.5 + (lengths / lengths.max()) * 3.0

    schnorr_proof_size = np.full_like(lengths, fill_value=0.096, dtype=float)
    snark_proof_size = np.full_like(lengths, fill_value=32.0, dtype=float)

    schnorr_verify = 2.5 + lengths * 0.008
    snark_verify = 12.0 + lengths * 0.02

    schnorr_cpu_cost = 3.0 + lengths * 0.005
    snark_cpu_cost = 9.0 + lengths * 0.015

    schnorr_energy = schnorr_total * 0.0025
    snark_energy = snark_total * 0.01

    schnorr_secure_bits = np.full_like(lengths, 256, dtype=float)
    snark_secure_bits = np.full_like(lengths, 128, dtype=float)

    schnorr_symmetric = np.full_like(lengths, 128, dtype=float)
    snark_symmetric = np.full_like(lengths, 80, dtype=float)

    schnorr_grover = np.full_like(lengths, 128, dtype=float)
    snark_grover = np.full_like(lengths, 64, dtype=float)

    schnorr_privacy = np.full_like(lengths, 7.0, dtype=float)
    snark_privacy = np.full_like(lengths, 10.0, dtype=float)

    schnorr_assumptions = np.full_like(lengths, 1, dtype=int)
    snark_assumptions = np.full_like(lengths, 3, dtype=int)

    schnorr_pq = np.linspace(6.0, 6.5, len(lengths))
    snark_pq = np.linspace(5.0, 5.5, len(lengths))

    schnorr_audit = np.full_like(lengths, 9.0, dtype=float)
    snark_audit = np.full_like(lengths, 7.0, dtype=float)

    schnorr_success = np.full_like(lengths, 100.0, dtype=float)
    snark_success = np.full_like(lengths, 99.5, dtype=float)

    schnorr_efficiency = (schnorr_throughput / schnorr_ram) / schnorr_latency_ratio
    snark_efficiency = (snark_throughput / snark_ram) / snark_latency_ratio

    return {
        "ZK-Schnorr": ProtocolMetrics(
            message_lengths=lengths.tolist(),
            embed_time_ms=schnorr_embed.tolist(),
            extract_time_ms=schnorr_extract.tolist(),
            total_time_ms=schnorr_total.tolist(),
            throughput_kbps=schnorr_throughput.tolist(),
            latency_ratio=schnorr_latency_ratio.tolist(),
            ram_usage_mb=schnorr_ram.tolist(),
            proof_size_kb=schnorr_proof_size.tolist(),
            verification_time_ms=schnorr_verify.tolist(),
            cpu_cost_score=schnorr_cpu_cost.tolist(),
            energy_cost_j=schnorr_energy.tolist(),
            security_bits=schnorr_secure_bits.tolist(),
            symmetric_equivalent_bits=schnorr_symmetric.tolist(),
            grover_adjusted_bits=schnorr_grover.tolist(),
            privacy_score=schnorr_privacy.tolist(),
            assumption_count=schnorr_assumptions.tolist(),
            post_quantum_readiness=schnorr_pq.tolist(),
            audit_maturity=schnorr_audit.tolist(),
            success_rate=schnorr_success.tolist(),
            efficiency_score=schnorr_efficiency.tolist(),
        ),
        "ZK-SNARK": ProtocolMetrics(
            message_lengths=lengths.tolist(),
            embed_time_ms=snark_embed.tolist(),
            extract_time_ms=snark_extract.tolist(),
            total_time_ms=snark_total.tolist(),
            throughput_kbps=snark_throughput.tolist(),
            latency_ratio=snark_latency_ratio.tolist(),
            ram_usage_mb=snark_ram.tolist(),
            proof_size_kb=snark_proof_size.tolist(),
            verification_time_ms=snark_verify.tolist(),
            cpu_cost_score=snark_cpu_cost.tolist(),
            energy_cost_j=snark_energy.tolist(),
            security_bits=snark_secure_bits.tolist(),
            symmetric_equivalent_bits=snark_symmetric.tolist(),
            grover_adjusted_bits=snark_grover.tolist(),
            privacy_score=snark_privacy.tolist(),
            assumption_count=snark_assumptions.tolist(),
            post_quantum_readiness=snark_pq.tolist(),
            audit_maturity=snark_audit.tolist(),
            success_rate=snark_success.tolist(),
            efficiency_score=snark_efficiency.tolist(),
        ),
    }


def plot_dual_line(ax, x, schnorr_data, snark_data, xlabel, ylabel, title):
    ax.plot(x, schnorr_data, 'o-', color='#2E86AB', linewidth=2.2,
            markersize=5, label='ZK-Schnorr')
    ax.plot(x, snark_data, 's--', color='#A23B72', linewidth=2.2,
            markersize=5, label='ZK-SNARK')
    ax.set_xlabel(xlabel, fontsize=10, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=10, fontweight='bold')
    ax.set_title(title, fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.3)
    legend = ax.legend(loc='upper left', fontsize=8, frameon=True,
                       fancybox=True, facecolor='white', framealpha=0.85)
    legend.get_frame().set_edgecolor('#4F4F4F')


def create_dashboard(protocols: Dict[str, ProtocolMetrics], timestamp: str):
    """Generate the 4×5 comparative dashboard."""
    fig = plt.figure(figsize=(26, 18))
    gs = fig.add_gridspec(4, 5, hspace=0.45, wspace=0.35)

    lengths = protocols["ZK-Schnorr"].message_lengths
    x = lengths
    xlabel = 'Message Length (characters)'

    schnorr = protocols["ZK-Schnorr"]
    snark = protocols["ZK-SNARK"]

    # Row 1: Performance
    plot_dual_line(fig.add_subplot(gs[0, 0]), x, schnorr.embed_time_ms, snark.embed_time_ms,
                   xlabel, 'Embedding Time (ms)',
                   '1. Embedding Latency')
    plot_dual_line(fig.add_subplot(gs[0, 1]), x, schnorr.extract_time_ms, snark.extract_time_ms,
                   xlabel, 'Extraction Time (ms)',
                   '2. Extraction Latency')
    plot_dual_line(fig.add_subplot(gs[0, 2]), x, schnorr.total_time_ms, snark.total_time_ms,
                   xlabel, 'Total Time (ms)',
                   '3. Total Round-trip Latency')
    plot_dual_line(fig.add_subplot(gs[0, 3]), x, schnorr.throughput_kbps, snark.throughput_kbps,
                   xlabel, 'Throughput (KB/s)',
                   '4. Throughput per Character')
    plot_dual_line(fig.add_subplot(gs[0, 4]), x, schnorr.latency_ratio, snark.latency_ratio,
                   xlabel, 'Normalised Latency',
                   '5. Latency Percentile (0-1)')

    # Row 2: Cost footprint
    plot_dual_line(fig.add_subplot(gs[1, 0]), x, schnorr.ram_usage_mb, snark.ram_usage_mb,
                   xlabel, 'RAM (MB)',
                   '6. RAM Footprint')
    plot_dual_line(fig.add_subplot(gs[1, 1]), x, schnorr.proof_size_kb, snark.proof_size_kb,
                   xlabel, 'Proof Size (KB)',
                   '7. Proof Artifact Size')
    plot_dual_line(fig.add_subplot(gs[1, 2]), x, schnorr.verification_time_ms, snark.verification_time_ms,
                   xlabel, 'Verification Time (ms)',
                   '8. Verification Latency')
    plot_dual_line(fig.add_subplot(gs[1, 3]), x, schnorr.cpu_cost_score, snark.cpu_cost_score,
                   xlabel, 'CPU Score (arbitrary)',
                   '9. CPU Cycle Cost Index')
    plot_dual_line(fig.add_subplot(gs[1, 4]), x, schnorr.energy_cost_j, snark.energy_cost_j,
                   xlabel, 'Energy (J)',
                   '10. Estimated Energy Cost')

    # Row 3: Security depth
    plot_dual_line(fig.add_subplot(gs[2, 0]), x, schnorr.security_bits, snark.security_bits,
                   xlabel, 'Security Bits',
                   '11. Classical Security Bits')
    plot_dual_line(fig.add_subplot(gs[2, 1]), x, schnorr.symmetric_equivalent_bits, snark.symmetric_equivalent_bits,
                   xlabel, 'AES-equivalent Bits',
                   '12. Symmetric Equivalent Security')
    plot_dual_line(fig.add_subplot(gs[2, 2]), x, schnorr.grover_adjusted_bits, snark.grover_adjusted_bits,
                   xlabel, 'Adjusted Bits',
                   '13. Grover-adjusted Security')
    plot_dual_line(fig.add_subplot(gs[2, 3]), x, schnorr.privacy_score, snark.privacy_score,
                   xlabel, 'Privacy Score (0-10)',
                   '14. Witness Privacy Level')
    plot_dual_line(fig.add_subplot(gs[2, 4]), x, schnorr.assumption_count, snark.assumption_count,
                   xlabel, 'Assumption Count',
                   '15. Independent Assumptions')

    # Row 4: Trade-off and reliability
    plot_dual_line(fig.add_subplot(gs[3, 0]), x, schnorr.post_quantum_readiness, snark.post_quantum_readiness,
                   xlabel, 'Readiness Score (0-10)',
                   '16. Post-Quantum Readiness')
    plot_dual_line(fig.add_subplot(gs[3, 1]), x, schnorr.audit_maturity, snark.audit_maturity,
                   xlabel, 'Audit Score (0-10)',
                   '17. Ecosystem Maturity')
    plot_dual_line(fig.add_subplot(gs[3, 2]), x, schnorr.success_rate, snark.success_rate,
                   xlabel, 'Success (%)',
                   '18. Proof Success Consistency')
    plot_dual_line(fig.add_subplot(gs[3, 3]), x, schnorr.efficiency_score, snark.efficiency_score,
                   xlabel, 'Efficiency Score',
                   '19. Efficiency Index\n(Throughput / RAM / Latency)')

    ax_summary = fig.add_subplot(gs[3, 4])
    ax_summary.axis('off')

    schnorr_avg = np.mean(schnorr.efficiency_score)
    snark_avg = np.mean(snark.efficiency_score)

    summary_lines = [
        "📊 COMPARATIVE SUMMARY",
        "",
        f"Message lengths analysed      : {len(lengths)} points (50 → 1000 chars)",
        f"Average latency (Schnorr)      : {np.mean(schnorr.total_time_ms):.2f} ms",
        f"Average latency (SNARK)        : {np.mean(snark.total_time_ms):.2f} ms",
        f"Average RAM (Schnorr)          : {np.mean(schnorr.ram_usage_mb):.2f} MB",
        f"Average RAM (SNARK)            : {np.mean(snark.ram_usage_mb):.2f} MB",
        f"Proof size (Schnorr)           : {schnorr.proof_size_kb[0]:.3f} KB",
        f"Proof size (SNARK)             : {snark.proof_size_kb[0]:.1f} KB",
        "",
        f"Security margin (Schnorr)      : {schnorr.security_bits[0]:.0f} bits classical",
        f"Security margin (SNARK)        : {snark.security_bits[0]:.0f} bits classical",
        "",
        f"Efficiency score (Schnorr)     : {schnorr_avg:.1f}",
        f"Efficiency score (SNARK)       : {snark_avg:.1f}",
        "",
        "Trade-off insights:",
        "  • ZK-Schnorr excels in performance, RAM footprint, and simplicity.",
        "  • ZK-SNARK provides stronger privacy but at significantly higher cost.",
        "  • Post-quantum readiness remains an open concern for both stacks."
    ]

    ax_summary.text(
        0.0, 0.5, "\n".join(summary_lines),
        fontsize=11, ha='left', va='center', family='monospace',
        bbox=dict(boxstyle='round', facecolor='#FFF7D6', alpha=0.9,
                  edgecolor='#333333', linewidth=1.5)
    )

    plt.suptitle(
        'ZK-Schnorr vs ZK-SNARK: Performance, Cost, and Security Trade-offs\n'
        f'20 comparative points · Generated {timestamp}',
        fontsize=18, fontweight='bold', y=0.995
    )
    plt.tight_layout(rect=[0, 0.04, 1, 0.99])

    dashboard_file = OUTPUT_DIR / f"comparative_tradeoffs_{timestamp}.png"
    plt.savefig(dashboard_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Dashboard image saved: {dashboard_file.relative_to(Path.cwd())}")

    pdf_file = dashboard_file.with_suffix('.pdf')
    plt.savefig(pdf_file, format='pdf', bbox_inches='tight', facecolor='white')
    print(f"✅ Dashboard PDF saved: {pdf_file.relative_to(Path.cwd())}")

    plt.close()


def save_metrics_json(protocols: Dict[str, ProtocolMetrics], timestamp: str):
    """Persist the synthetic benchmark data for reproducibility."""
    payload = {
        "timestamp": timestamp,
        "description": "Synthetic comparative metrics for ZK-Schnorr vs ZK-SNARK",
        "message_length_range": [min(protocols["ZK-Schnorr"].message_lengths),
                                 max(protocols["ZK-Schnorr"].message_lengths)],
        "protocols": {name: asdict(metrics) for name, metrics in protocols.items()}
    }

    json_file = OUTPUT_DIR / "data" / f"comparative_tradeoffs_{timestamp}.json"
    json_file.parent.mkdir(parents=True, exist_ok=True)
    with open(json_file, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f"💾 Saved synthetic metrics: {json_file.relative_to(Path.cwd())}")


def main():
    print("=" * 90)
    print("COMPARATIVE TRADE-OFF DASHBOARD: ZK-SCHNORR vs ZK-SNARK")
    print("=" * 90)

    message_lengths = np.linspace(50, 1000, 20, dtype=int)
    protocols = generate_protocol_metrics(message_lengths)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_metrics_json(protocols, timestamp)
    create_dashboard(protocols, timestamp)

    print("\n✅ Detailed comparative dashboard generated successfully.")
    print(f"   → Data & figures stored under: {OUTPUT_DIR.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
