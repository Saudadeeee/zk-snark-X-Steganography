#!/usr/bin/env python3
"""
Security Trade-offs Comparison: ZK-SNARK vs ZK-Schnorr
Simple line charts showing key security and performance metrics
"""

import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "comparison_results" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def create_security_comparison():
    """Create comprehensive security comparison charts"""
    
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle('Security & Performance Trade-offs: ZK-SNARK vs ZK-Schnorr',
                 fontsize=16, fontweight='bold', y=0.98)
    
    colors = {
        'Schnorr': '#2E86AB',
        'SNARK': '#A23B72',
        'Guide': '#7F7F7F'
    }
    
    def plot_line(ax, labels, schnorr_vals, snark_vals, ylabel, title,
                  schnorr_notes, snark_notes, unit, ylim=None, guides=None):
        """Helper to draw dual-line comparisons with detailed annotations."""
        x = np.arange(len(labels))
        ax.plot(x, schnorr_vals, 'o-', color=colors['Schnorr'], linewidth=2.8,
                markersize=8, label='ZK-Schnorr')
        ax.plot(x, snark_vals, 's--', color=colors['SNARK'], linewidth=2.8,
                markersize=8, label='ZK-SNARK')
        
        for xpos, value, note in zip(x, schnorr_vals, schnorr_notes):
            text = f'{value}{unit}\n{note}' if unit else f'{value}\n{note}'
            ax.annotate(text, xy=(xpos, value), xytext=(-32, 12),
                        textcoords='offset points', ha='right', va='bottom',
                        fontsize=9, fontweight='bold', color=colors['Schnorr'],
                        bbox=dict(boxstyle='round,pad=0.3', edgecolor=colors['Schnorr'],
                                  facecolor='#E6F0FA', alpha=0.65))
        
        for xpos, value, note in zip(x, snark_vals, snark_notes):
            text = f'{value}{unit}\n{note}' if unit else f'{value}\n{note}'
            ax.annotate(text, xy=(xpos, value), xytext=(32, -18),
                        textcoords='offset points', ha='left', va='top',
                        fontsize=9, fontweight='bold', color=colors['SNARK'],
                        bbox=dict(boxstyle='round,pad=0.3', edgecolor=colors['SNARK'],
                                  facecolor='#F9E6F0', alpha=0.65))
        
        if guides:
            for guide_val, guide_label in guides:
                ax.axhline(y=guide_val, color=colors['Guide'], linestyle='--',
                           linewidth=1.2, alpha=0.5)
                ax.text(x[-1] + 0.1, guide_val, guide_label,
                        fontsize=9, color=colors['Guide'], va='center')
        
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=11, fontweight='bold')
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.grid(True, alpha=0.3)
        if ylim:
            ax.set_ylim(*ylim)
        ax.legend(fontsize=9, loc='best')
    
    # Chart 1: Computational Security (bits)
    plot_line(
        axes[0, 0],
        labels=['Classical bit security', 'Symmetric equivalent', 'Grover-adjusted (PQ)'],
        schnorr_vals=[256, 128, 128],
        snark_vals=[128, 80, 64],
        ylabel='Security Strength',
        title='1. Computational Security Benchmarks',
        schnorr_notes=[
            'Discrete log hardness',
            '≈ AES-128 resilience',
            'Post-quantum plan required'
        ],
        snark_notes=[
            'Pairing curve baseline',
            '≈ AES-80 equivalent',
            'Grover halves exponent'
        ],
        unit=' bits',
        ylim=(0, 280),
        guides=[(128, 'Recommended floor: 128 bits')]
    )
    
    # Chart 2: Setup Requirements (complexity score)
    plot_line(
        axes[0, 1],
        labels=['Trusted parties involved', 'Setup phases', 'Universality score'],
        schnorr_vals=[0, 0, 10],
        snark_vals=[10, 8, 3],
        ylabel='Complexity & Reuse Score',
        title='2. Trusted Setup Requirements',
        schnorr_notes=[
            'No coordinator required',
            'No ceremony, deterministic',
            'Universal across circuits'
        ],
        snark_notes=[
            'Requires MPC of n parties',
            'Powers of Tau + circuit-specific',
            'Reuse limited to circuit'
        ],
        unit=' /10',
        ylim=(-1, 12)
    )
    
    # Chart 3: Zero-Knowledge Strength
    plot_line(
        axes[0, 2],
        labels=['Witness leakage', 'Transcript unlinkability', 'Simulation soundness'],
        schnorr_vals=[6, 7, 7],
        snark_vals=[10, 9, 10],
        ylabel='Privacy Level',
        title='3. Zero-Knowledge Strength (0-10)',
        schnorr_notes=[
            'Statement exposure present',
            'Reusable signature structure',
            'Sigma protocol simulator'
        ],
        snark_notes=[
            'Witness perfectly hidden',
            'Uses CRS for unlinkability',
            'Strong simulation ZK'
        ],
        unit=' /10',
        ylim=(0, 12)
    )
    
    # Chart 4: Attack Resistance per Threat
    plot_line(
        axes[1, 0],
        labels=['Brute force', 'Quantum future', 'Side channel', 'Replay attack'],
        schnorr_vals=[10, 3, 8, 10],
        snark_vals=[9, 2, 7, 10],
        ylabel='Resistance Score (0-10)',
        title='4. Resistance Across Threat Models',
        schnorr_notes=[
            '2^256 operations',
            'Needs PQ hardening',
            'Constant-time signatures',
            'Fresh nonces each proof'
        ],
        snark_notes=[
            '≈2^128 operations',
            'Relies on pairings',
            'Circuit leakage risk',
            'Includes unique commitments'
        ],
        unit=' /10',
        ylim=(0, 12),
        guides=[(5, 'Baseline acceptable security')]
    )
    
    # Chart 5: Cryptographic Assumptions
    plot_line(
        axes[1, 1],
        labels=['Core assumptions', 'Exotic primitives', 'Knowledge-of-exponent'],
        schnorr_vals=[1, 0, 0],
        snark_vals=[3, 2, 1],
        ylabel='Assumption Count / Presence',
        title='5. Cryptographic Foundations',
        schnorr_notes=[
            'Discrete Log over prime fields',
            'No pairings or bilinear maps',
            'No knowledge-of-exponent'
        ],
        snark_notes=[
            'DLP + Pairings + Algebraic Group Model',
            'Pairings & elliptic curve twists',
            'Knowledge-of-exponent needed'
        ],
        unit=' units',
        ylim=(-1, 5)
    )
    
    # Chart 6: Overall Security Profile
    plot_line(
        axes[1, 2],
        labels=['Security Level', 'Privacy', 'Simplicity', 'Proven Security', 'Future-Proofing'],
        schnorr_vals=[10, 7, 10, 9, 6],
        snark_vals=[9, 10, 5, 7, 5],
        ylabel='Composite Score (0-10)',
        title='6. Multi-factor Security Profile',
        schnorr_notes=[
            'Large classical margin',
            'Partial knowledge hiding',
            'Few moving parts',
            'Long production use',
            'PQ migration needed'
        ],
        snark_notes=[
            'Pairing curve security',
            'Full witness privacy',
            'Circuit complexity',
            'Younger deployments',
            'PQ migration needed'
        ],
        unit=' /10',
        ylim=(0, 12),
        guides=[(5, 'Minimum acceptable score')]
    )
    
    # ============================================================================
    # Adjust layout and save
    # ============================================================================
    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    
    output_file = OUTPUT_DIR / "security_tradeoffs_comparison.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f'✓ Security comparison chart saved: {output_file}')
    
    # Also save as PDF
    output_pdf = output_file.with_suffix('.pdf')
    plt.savefig(output_pdf, bbox_inches='tight', facecolor='white')
    print(f'✓ PDF version saved: {output_pdf}')
    
    plt.close()
    
    # Print summary
    print("\n" + "="*80)
    print("SECURITY COMPARISON SUMMARY")
    print("="*80)
    print("\n📊 6 Key Metrics Compared:")
    print("  1. Computational Security: Schnorr 256-bit vs SNARK 128-bit")
    print("  2. Setup Requirements: Schnorr (none) vs SNARK (trusted)")
    print("  3. Privacy Guarantee: Schnorr (limited) vs SNARK (full)")
    print("  4. Attack Resistance: Both high, quantum-vulnerable")
    print("  5. Cryptographic Foundation: Schnorr (1 assumption) vs SNARK (3)")
    print("  6. Overall Profile: Balanced trade-offs")
    print("\n🎯 Key Takeaways:")
    print("  • Schnorr: Simpler, proven, no setup, higher classical security")
    print("  • SNARK: Full privacy, complex circuits, requires trusted setup")
    print("  • Both: Vulnerable to quantum attacks (future concern)")
    print("="*80)


def create_line_chart_comparison():
    """Create line chart showing security metrics evolution"""
    
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle('Security Properties: Progressive Comparison', 
                 fontsize=16, fontweight='bold')
    
    colors = {
        'Schnorr': '#2E86AB',
        'SNARK': '#A23B72'
    }
    
    # ============================================================================
    # Chart 1: Security Properties (Line Chart)
    # ============================================================================
    ax1 = axes[0]
    
    properties = ['Security\nLevel', 'Privacy', 'Simplicity', 'No\nSetup', 'Proven\nTrack', 'Quantum\nResist']
    x_pos = np.arange(len(properties))
    
    # Scores (0-10)
    schnorr_line = [10, 7, 10, 10, 9, 3]
    snark_line = [9, 10, 5, 0, 7, 2]
    
    ax1.plot(x_pos, schnorr_line, 'o-', label='ZK-Schnorr', 
            color=colors['Schnorr'], linewidth=3, markersize=10)
    ax1.plot(x_pos, snark_line, 's-', label='ZK-SNARK',
            color=colors['SNARK'], linewidth=3, markersize=10)
    
    # Fill areas
    ax1.fill_between(x_pos, schnorr_line, alpha=0.2, color=colors['Schnorr'])
    ax1.fill_between(x_pos, snark_line, alpha=0.2, color=colors['SNARK'])
    
    schnorr_line_details = [
        '256-bit headroom',
        'Knowledge proofs',
        'Minimal arithmetic',
        'Deterministic setup',
        'Battle-tested',
        'Not quantum-safe'
    ]
    snark_line_details = [
        'Pairing hardness',
        'Full witness hiding',
        'Circuit overhead',
        'Trusted ceremony',
        'Younger audits',
        'Needs PQ upgrade'
    ]
    for idx, (score, detail) in enumerate(zip(schnorr_line, schnorr_line_details)):
        ax1.annotate(f'{score}/10\n{detail}',
                     xy=(idx, score),
                     xytext=(-25, 10),
                     textcoords='offset points',
                     ha='right',
                     va='bottom',
                     fontsize=9,
                     fontweight='bold',
                     color=colors['Schnorr'])
    for idx, (score, detail) in enumerate(zip(snark_line, snark_line_details)):
        ax1.annotate(f'{score}/10\n{detail}',
                     xy=(idx, score),
                     xytext=(25, -18),
                     textcoords='offset points',
                     ha='left',
                     va='top',
                     fontsize=9,
                     fontweight='bold',
                     color=colors['SNARK'])
    
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(properties, fontsize=10)
    ax1.set_ylabel('Score (0-10)', fontsize=12, fontweight='bold')
    ax1.set_title('Security Properties Profile', fontsize=13, fontweight='bold')
    ax1.legend(fontsize=11, loc='lower left')
    ax1.set_ylim(-1, 12)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=5, color='orange', linestyle='--', alpha=0.5, linewidth=2, label='Threshold')
    
    # ============================================================================
    # Chart 2: Trade-off Analysis (Winner in each category)
    # ============================================================================
    ax2 = axes[1]
    
    categories = ['Security\nBits', 'Privacy\nLevel', 'Setup\nSimple', 'Crypto\nSimple', 
                  'Proof\nSize', 'Speed']
    
    # +1 for Schnorr win, -1 for SNARK win, 0 for tie
    winners = [1, -1, 1, 1, 1, 1]  # Schnorr wins most except privacy
    
    colors_bar = [colors['Schnorr'] if w > 0 else colors['SNARK'] for w in winners]
    
    bars = ax2.bar(categories, [abs(w) for w in winners], 
                   color=colors_bar, alpha=0.8, edgecolor='black', linewidth=2)
    
    winner_details = [
        'Schnorr\n256-bit security (+128-bit margin)',
        'SNARK\nFull witness privacy',
        'Schnorr\nNo trusted parties',
        'Schnorr\nSingle DLP assumption',
        'Schnorr\n≈96 byte proofs',
        'Schnorr\n~1200× faster proving'
    ]
    for bar, detail in zip(bars, winner_details):
        ax2.annotate(detail,
                     xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                     xytext=(0, 8),
                     textcoords='offset points',
                     ha='center',
                     va='bottom',
                     fontsize=9,
                     fontweight='bold')
    
    ax2.set_ylabel('Winner (1 = has advantage)', fontsize=12, fontweight='bold')
    ax2.set_title('Category Winners', fontsize=13, fontweight='bold')
    ax2.set_ylim(0, 1.3)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=colors['Schnorr'], label='ZK-Schnorr Wins'),
        Patch(facecolor=colors['SNARK'], label='ZK-SNARK Wins')
    ]
    ax2.legend(handles=legend_elements, fontsize=11, loc='upper right')
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    
    output_file = OUTPUT_DIR / "security_line_comparison.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f'\n✓ Line chart comparison saved: {output_file}')
    
    plt.close()
    
    print("\n📈 Winner Count:")
    schnorr_wins = sum(1 for w in winners if w > 0)
    snark_wins = sum(1 for w in winners if w < 0)
    print(f"  • ZK-Schnorr wins: {schnorr_wins}/6 categories")
    print(f"  • ZK-SNARK wins: {snark_wins}/6 categories")
    print(f"  • Winner: {'ZK-Schnorr' if schnorr_wins > snark_wins else 'ZK-SNARK'} (for this use case)")


if __name__ == "__main__":
    print("="*80)
    print("GENERATING SECURITY COMPARISON CHARTS")
    print("="*80)
    
    print("\n1. Creating comprehensive 6-panel comparison...")
    create_security_comparison()
    
    print("\n2. Creating line chart comparison...")
    create_line_chart_comparison()
    
    print("\n" + "="*80)
    print("✅ ALL CHARTS GENERATED SUCCESSFULLY")
    print("="*80)
    print("\nOutput files:")
    print("  • security_tradeoffs_comparison.png (6 panels)")
    print("  • security_tradeoffs_comparison.pdf (6 panels)")
    print("  • security_line_comparison.png (line charts)")
    print("="*80)
