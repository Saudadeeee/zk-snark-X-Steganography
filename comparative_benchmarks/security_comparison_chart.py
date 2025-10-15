#!/usr/bin/env python3
"""
Security Trade-offs Comparison: ZK-SNARK vs ZK-Schnorr
Simple line charts showing key security and performance metrics
"""

import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

def create_security_comparison():
    """Create comprehensive security comparison charts"""
    
    # Create figure with 2x3 subplots
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle('Security & Performance Trade-offs: ZK-SNARK vs ZK-Schnorr', 
                 fontsize=16, fontweight='bold', y=0.98)
    
    colors = {
        'Schnorr': '#2E86AB',
        'SNARK': '#A23B72',
        'Better': '#06A77D',
        'Worse': '#E63946'
    }
    
    # ============================================================================
    # Chart 1: Security Level (bits)
    # ============================================================================
    ax1 = axes[0, 0]
    
    protocols = ['ZK-Schnorr', 'ZK-SNARK\n(Groth16)']
    security_bits = [256, 128]  # DLP-256 vs pairing-based 128-bit
    
    bars = ax1.bar(protocols, security_bits, color=[colors['Schnorr'], colors['SNARK']], 
                   alpha=0.8, edgecolor='black', linewidth=2)
    
    # Add value labels
    for bar, value in zip(bars, security_bits):
        ax1.text(bar.get_x() + bar.get_width()/2, value + 5,
                f'{value} bits', ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    ax1.axhline(y=128, color='orange', linestyle='--', alpha=0.5, linewidth=2, label='Min Recommended (128-bit)')
    ax1.set_ylabel('Security Level (bits)', fontsize=11, fontweight='bold')
    ax1.set_title('1. Computational Security', fontsize=12, fontweight='bold')
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.set_ylim(0, 300)
    
    # ============================================================================
    # Chart 2: Setup Complexity
    # ============================================================================
    ax2 = axes[0, 1]
    
    setup_types = ['ZK-Schnorr', 'ZK-SNARK']
    setup_complexity = [0, 10]  # Schnorr: no setup, SNARK: trusted setup required
    
    bars = ax2.bar(setup_types, setup_complexity, 
                   color=[colors['Better'], colors['Worse']], 
                   alpha=0.8, edgecolor='black', linewidth=2)
    
    # Add labels
    labels = ['No Setup\nNeeded ✓', 'Trusted Setup\nRequired ✗']
    for bar, label, value in zip(bars, labels, setup_complexity):
        if value == 0:
            ax2.text(bar.get_x() + bar.get_width()/2, 1,
                    label, ha='center', va='bottom', fontsize=10, fontweight='bold')
        else:
            ax2.text(bar.get_x() + bar.get_width()/2, value + 0.3,
                    label, ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    ax2.set_ylabel('Setup Complexity (0-10 scale)', fontsize=11, fontweight='bold')
    ax2.set_title('2. Setup Requirements', fontsize=12, fontweight='bold')
    ax2.set_ylim(0, 12)
    ax2.grid(True, alpha=0.3, axis='y')
    
    # ============================================================================
    # Chart 3: Zero-Knowledge Property
    # ============================================================================
    ax3 = axes[0, 2]
    
    zk_types = ['ZK-Schnorr\n(Signature-based)', 'ZK-SNARK\n(Full ZK)']
    zk_level = [7, 10]  # Schnorr: proof of knowledge, SNARK: full zero-knowledge
    
    bars = ax3.bar(zk_types, zk_level, 
                   color=[colors['Schnorr'], colors['SNARK']], 
                   alpha=0.8, edgecolor='black', linewidth=2)
    
    # Add value labels
    labels_zk = ['Proof of Knowledge\n(Limited ZK)', 'Full Zero-Knowledge\n(Complete Privacy)']
    for bar, label, value in zip(bars, labels_zk, zk_level):
        ax3.text(bar.get_x() + bar.get_width()/2, value + 0.3,
                f'{value}/10\n{label}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax3.set_ylabel('Zero-Knowledge Level (0-10)', fontsize=11, fontweight='bold')
    ax3.set_title('3. Privacy Guarantee', fontsize=12, fontweight='bold')
    ax3.set_ylim(0, 12)
    ax3.grid(True, alpha=0.3, axis='y')
    
    # ============================================================================
    # Chart 4: Attack Resistance (multiple threats)
    # ============================================================================
    ax4 = axes[1, 0]
    
    threats = ['Brute\nForce', 'Quantum\n(Future)', 'Side\nChannel', 'Replay\nAttack']
    schnorr_resistance = [10, 3, 8, 10]  # High classical, low quantum, good side-channel
    snark_resistance = [9, 2, 7, 10]     # High classical, low quantum, moderate side-channel
    
    x = np.arange(len(threats))
    width = 0.35
    
    bars1 = ax4.bar(x - width/2, schnorr_resistance, width, label='ZK-Schnorr',
                    color=colors['Schnorr'], alpha=0.8, edgecolor='black', linewidth=1.5)
    bars2 = ax4.bar(x + width/2, snark_resistance, width, label='ZK-SNARK',
                    color=colors['SNARK'], alpha=0.8, edgecolor='black', linewidth=1.5)
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax4.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                    f'{int(height)}/10', ha='center', va='bottom', fontsize=8, fontweight='bold')
    
    ax4.set_ylabel('Resistance Level (0-10)', fontsize=11, fontweight='bold')
    ax4.set_title('4. Attack Resistance', fontsize=12, fontweight='bold')
    ax4.set_xticks(x)
    ax4.set_xticklabels(threats, fontsize=10)
    ax4.legend(fontsize=10, loc='upper right')
    ax4.set_ylim(0, 12)
    ax4.grid(True, alpha=0.3, axis='y')
    ax4.axhline(y=5, color='red', linestyle=':', alpha=0.3, linewidth=1)
    
    # ============================================================================
    # Chart 5: Cryptographic Assumptions
    # ============================================================================
    ax5 = axes[1, 1]
    
    assumption_complexity = {
        'ZK-Schnorr': 1,    # Only DLP
        'ZK-SNARK': 3       # DLP + pairing + knowledge-of-exponent
    }
    
    protocols_assume = list(assumption_complexity.keys())
    complexity_values = list(assumption_complexity.values())
    
    bars = ax5.bar(protocols_assume, complexity_values,
                   color=[colors['Better'], colors['Worse']], 
                   alpha=0.8, edgecolor='black', linewidth=2)
    
    # Add detailed labels
    labels_assume = ['1 Assumption:\nDLP-256\n(Simple ✓)', 
                     '3 Assumptions:\nDLP + Pairing +\nKoE (Complex ✗)']
    for bar, label, value in zip(bars, labels_assume, complexity_values):
        ax5.text(bar.get_x() + bar.get_width()/2, value + 0.1,
                label, ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax5.set_ylabel('Number of Assumptions', fontsize=11, fontweight='bold')
    ax5.set_title('5. Cryptographic Foundation', fontsize=12, fontweight='bold')
    ax5.set_ylim(0, 4)
    ax5.grid(True, alpha=0.3, axis='y')
    
    # ============================================================================
    # Chart 6: Overall Security Score (Radar-style as bar)
    # ============================================================================
    ax6 = axes[1, 2]
    
    categories = ['Security\nLevel', 'Privacy', 'Simplicity', 'Proven\nSecurity', 'Future-\nProof']
    
    # Scores out of 10
    schnorr_scores = [10, 7, 10, 9, 6]   # High security, moderate privacy, simple, proven, quantum-vulnerable
    snark_scores = [9, 10, 5, 7, 5]       # High security, full privacy, complex, less proven, quantum-vulnerable
    
    x = np.arange(len(categories))
    width = 0.35
    
    bars1 = ax6.bar(x - width/2, schnorr_scores, width, label='ZK-Schnorr',
                    color=colors['Schnorr'], alpha=0.8, edgecolor='black', linewidth=1.5)
    bars2 = ax6.bar(x + width/2, snark_scores, width, label='ZK-SNARK',
                    color=colors['SNARK'], alpha=0.8, edgecolor='black', linewidth=1.5)
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax6.text(bar.get_x() + bar.get_width()/2., height + 0.2,
                    f'{int(height)}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    ax6.set_ylabel('Score (0-10)', fontsize=11, fontweight='bold')
    ax6.set_title('6. Overall Security Profile', fontsize=12, fontweight='bold')
    ax6.set_xticks(x)
    ax6.set_xticklabels(categories, fontsize=9)
    ax6.legend(fontsize=10, loc='upper left')
    ax6.set_ylim(0, 12)
    ax6.grid(True, alpha=0.3, axis='y')
    ax6.axhline(y=5, color='orange', linestyle='--', alpha=0.3, linewidth=1, label='Threshold')
    
    # ============================================================================
    # Adjust layout and save
    # ============================================================================
    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    
    output_file = Path('comparative_benchmarks/comparison_results/figures/security_tradeoffs_comparison.png')
    output_file.parent.mkdir(parents=True, exist_ok=True)
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
    
    # Add value labels
    for i, (s, n) in enumerate(zip(schnorr_line, snark_line)):
        ax1.text(i, s + 0.3, f'{s}', ha='center', fontsize=10, 
                fontweight='bold', color=colors['Schnorr'])
        ax1.text(i, n - 0.7, f'{n}', ha='center', fontsize=10, 
                fontweight='bold', color=colors['SNARK'])
    
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
    
    # Add winner labels
    labels = ['Schnorr\n256-bit', 'SNARK\nFull ZK', 'Schnorr\nNo Setup', 
              'Schnorr\n1 Assumption', 'Schnorr\n96B', 'Schnorr\n1200× Faster']
    
    for bar, label in zip(bars, labels):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                label, ha='center', va='bottom', fontsize=9, fontweight='bold')
    
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
    
    output_file = Path('comparative_benchmarks/comparison_results/figures/security_line_comparison.png')
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
