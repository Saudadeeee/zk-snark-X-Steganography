#!/usr/bin/env python3
"""
Generate fixed visualization with log scale for panels A, B, C
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ComparativeResult:
    test_id: str
    protocol: str
    message_length: int
    image_size: list
    embedding_time_ms: float
    extraction_time_ms: float
    proof_generation_time_ms: float
    proof_verification_time_ms: float
    total_time_ms: float
    proof_size_bytes: int
    proof_size_kb: float
    psnr_db: float
    ssim: float
    mse: float
    embedding_success: bool
    proof_valid: bool
    message_integrity: bool
    setup_required: bool = False
    security_level: str = ''
    timestamp: str = ''


def main():
    # Load data
    data_file = Path('comparative_benchmarks/comparison_results/data/comparison_results_20251015_125516.json')
    
    with open(data_file, 'r') as f:
        data = json.load(f)
    
    # Parse results - use correct keys from JSON
    schnorr_results = [ComparativeResult(**r) for r in data['results']['ZK-Schnorr']]
    snark_results = [ComparativeResult(**r) for r in data['results']['ZK-SNARK']]
    
    print(f"✓ Loaded {len(schnorr_results)} Schnorr results")
    print(f"✓ Loaded {len(snark_results)} SNARK results")
    
    # Create figure
    fig = plt.figure(figsize=(20, 12))
    gs = GridSpec(3, 3, figure=fig, hspace=0.35, wspace=0.35)
    
    colors = {'ZK-Schnorr': '#2E86AB', 'ZK-SNARK': '#A23B72'}
    
    # Extract data
    msg_lengths_schnorr = [r.message_length for r in schnorr_results]
    msg_lengths_snark = [r.message_length for r in snark_results]
    
    # Plot 1: Proof Generation Time (LOG SCALE)
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(msg_lengths_schnorr, [r.proof_generation_time_ms for r in schnorr_results],
            'o-', label='ZK-Schnorr', color=colors['ZK-Schnorr'], linewidth=2, markersize=8)
    ax1.plot(msg_lengths_snark, [r.proof_generation_time_ms for r in snark_results],
            's-', label='ZK-SNARK', color=colors['ZK-SNARK'], linewidth=2, markersize=8)
    ax1.set_xlabel('Message Length (chars)', fontsize=11)
    ax1.set_ylabel('Proof Generation Time (ms)', fontsize=11)
    ax1.set_title('A. Proof Generation Performance (log scale)', fontsize=12, fontweight='bold')
    ax1.set_yscale('log')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3, which='both')
    
    # Plot 2: Proof Verification Time (LOG SCALE)
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(msg_lengths_schnorr, [r.proof_verification_time_ms for r in schnorr_results],
            'o-', label='ZK-Schnorr', color=colors['ZK-Schnorr'], linewidth=2, markersize=8)
    ax2.plot(msg_lengths_snark, [r.proof_verification_time_ms for r in snark_results],
            's-', label='ZK-SNARK', color=colors['ZK-SNARK'], linewidth=2, markersize=8)
    ax2.set_xlabel('Message Length (chars)', fontsize=11)
    ax2.set_ylabel('Verification Time (ms)', fontsize=11)
    ax2.set_title('B. Proof Verification Performance (log scale)', fontsize=12, fontweight='bold')
    ax2.set_yscale('log')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3, which='both')
    
    # Plot 3: Proof Size (LOG SCALE)
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.plot(msg_lengths_schnorr, [r.proof_size_bytes for r in schnorr_results],
            'o-', label='ZK-Schnorr', color=colors['ZK-Schnorr'], linewidth=2, markersize=8)
    ax3.plot(msg_lengths_snark, [r.proof_size_bytes for r in snark_results],
            's-', label='ZK-SNARK', color=colors['ZK-SNARK'], linewidth=2, markersize=8)
    ax3.set_xlabel('Message Length (chars)', fontsize=11)
    ax3.set_ylabel('Proof Size (bytes)', fontsize=11)
    ax3.set_title('C. Proof Size Comparison (log scale)', fontsize=12, fontweight='bold')
    ax3.set_yscale('log')
    ax3.legend(fontsize=10)
    ax3.grid(True, alpha=0.3, which='both')
    
    # Plot 4: Total Time
    ax4 = fig.add_subplot(gs[1, 0])
    ax4.plot(msg_lengths_schnorr, [r.total_time_ms for r in schnorr_results],
            'o-', label='ZK-Schnorr', color=colors['ZK-Schnorr'], linewidth=2, markersize=8)
    ax4.plot(msg_lengths_snark, [r.total_time_ms for r in snark_results],
            's-', label='ZK-SNARK', color=colors['ZK-SNARK'], linewidth=2, markersize=8)
    ax4.set_xlabel('Message Length (chars)', fontsize=11)
    ax4.set_ylabel('Total Time (ms)', fontsize=11)
    ax4.set_title('D. Total Processing Time', fontsize=12, fontweight='bold')
    ax4.legend(fontsize=10)
    ax4.grid(True, alpha=0.3)
    
    # Plot 5: PSNR Comparison
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.plot(msg_lengths_schnorr, [r.psnr_db for r in schnorr_results],
            'o-', label='ZK-Schnorr', color=colors['ZK-Schnorr'], linewidth=2, markersize=8)
    ax5.plot(msg_lengths_snark, [r.psnr_db for r in snark_results],
            's-', label='ZK-SNARK', color=colors['ZK-SNARK'], linewidth=2, markersize=8)
    ax5.axhline(y=40, color='red', linestyle='--', alpha=0.5, label='Imperceptible')
    ax5.set_xlabel('Message Length (chars)', fontsize=11)
    ax5.set_ylabel('PSNR (dB)', fontsize=11)
    ax5.set_title('E. Image Quality (PSNR)', fontsize=12, fontweight='bold')
    ax5.legend(fontsize=10)
    ax5.grid(True, alpha=0.3)
    
    # Plot 6: Speedup Factor
    ax6 = fig.add_subplot(gs[1, 2])
    speedup = [snark_results[i].proof_generation_time_ms / schnorr_results[i].proof_generation_time_ms 
               for i in range(len(schnorr_results))]
    ax6.plot(msg_lengths_schnorr, speedup, 'o-', color='#06A77D', linewidth=2, markersize=8)
    ax6.axhline(y=1, color='red', linestyle='--', alpha=0.5, label='Equal performance')
    ax6.set_xlabel('Message Length (chars)', fontsize=11)
    ax6.set_ylabel('Speedup Factor (SNARK/Schnorr)', fontsize=11)
    ax6.set_title('F. Schnorr Speedup vs SNARK', fontsize=12, fontweight='bold')
    ax6.legend(fontsize=10)
    ax6.grid(True, alpha=0.3)
    
    # Add text with actual speedup values
    avg_speedup = np.mean(speedup)
    ax6.text(0.95, 0.95, f'Avg: {avg_speedup:.0f}×', 
            transform=ax6.transAxes, fontsize=10, verticalalignment='top',
            horizontalalignment='right', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Plot 7: Size Ratio
    ax7 = fig.add_subplot(gs[2, 0])
    size_ratio = [snark_results[i].proof_size_bytes / schnorr_results[i].proof_size_bytes 
                  for i in range(len(schnorr_results))]
    ax7.plot(msg_lengths_schnorr, size_ratio, 'o-', color='#F18F01', linewidth=2, markersize=8)
    ax7.axhline(y=1, color='red', linestyle='--', alpha=0.5, label='Equal size')
    ax7.set_xlabel('Message Length (chars)', fontsize=11)
    ax7.set_ylabel('Size Ratio (SNARK/Schnorr)', fontsize=11)
    ax7.set_title('G. Proof Size Ratio', fontsize=12, fontweight='bold')
    ax7.legend(fontsize=10)
    ax7.grid(True, alpha=0.3)
    
    # Add text with size ratio range
    min_ratio = min(size_ratio)
    max_ratio = max(size_ratio)
    ax7.text(0.95, 0.95, f'{min_ratio:.1f}× - {max_ratio:.1f}×', 
            transform=ax7.transAxes, fontsize=10, verticalalignment='top',
            horizontalalignment='right', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Plot 8: Bar chart
    ax8 = fig.add_subplot(gs[2, 1])
    metrics = ['Proof Gen\n(ms)', 'Proof Verify\n(ms)', 'Proof Size\n(bytes)']
    schnorr_avg = [
        np.mean([r.proof_generation_time_ms for r in schnorr_results]),
        np.mean([r.proof_verification_time_ms for r in schnorr_results]),
        np.mean([r.proof_size_bytes for r in schnorr_results])
    ]
    snark_avg = [
        np.mean([r.proof_generation_time_ms for r in snark_results]),
        np.mean([r.proof_verification_time_ms for r in snark_results]),
        np.mean([r.proof_size_bytes for r in snark_results])
    ]
    
    x = np.arange(len(metrics))
    width = 0.35
    ax8.bar(x - width/2, schnorr_avg, width, label='ZK-Schnorr', color=colors['ZK-Schnorr'], alpha=0.8)
    ax8.bar(x + width/2, snark_avg, width, label='ZK-SNARK', color=colors['ZK-SNARK'], alpha=0.8)
    ax8.set_ylabel('Value', fontsize=11)
    ax8.set_title('H. Average Metrics Comparison', fontsize=12, fontweight='bold')
    ax8.set_xticks(x)
    ax8.set_xticklabels(metrics, fontsize=9)
    ax8.legend(fontsize=10)
    ax8.grid(True, alpha=0.3, axis='y')
    
    # Plot 9: Summary table
    ax9 = fig.add_subplot(gs[2, 2])
    ax9.axis('off')
    
    summary_data = [
        ['Metric', 'ZK-Schnorr', 'ZK-SNARK', 'Winner'],
        ['Proof Size', f'{int(schnorr_avg[2])} B', f'{int(snark_avg[2])} B', '✓ Schnorr'],
        ['Proof Gen', f'{schnorr_avg[0]:.2f} ms', f'{snark_avg[0]:.2f} ms', '✓ Schnorr'],
        ['Proof Verify', f'{schnorr_avg[1]:.2f} ms', f'{snark_avg[1]:.2f} ms', '✓ Schnorr'],
        ['Setup Req.', 'No', 'Yes', '✓ Schnorr'],
        ['Security', 'DLP-256', 'Groth16', '≈ Equal']
    ]
    
    table = ax9.table(cellText=summary_data, cellLoc='center', loc='center',
                     bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 2)
    
    for i in range(4):
        table[(0, i)].set_facecolor('#4472C4')
        table[(0, i)].set_text_props(weight='bold', color='white')
    
    ax9.set_title('I. Summary Comparison', fontsize=12, fontweight='bold', pad=20)
    
    plt.suptitle('ZK-SNARK vs ZK-Schnorr: Comprehensive Comparison', 
                fontsize=16, fontweight='bold', y=0.995)
    
    # Save
    output_file = Path('comparative_benchmarks/comparison_results/figures/snark_vs_schnorr_comparison_fixed.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f'\n✓ Fixed visualization saved: {output_file}')
    
    # Print data summary
    print(f'\n{"="*80}')
    print('DATA SUMMARY')
    print(f'{"="*80}')
    print(f'\nZK-Schnorr:')
    print(f'  Proof generation: {schnorr_avg[0]:.3f} ms')
    print(f'  Proof verification: {schnorr_avg[1]:.3f} ms')
    print(f'  Proof size: {schnorr_avg[2]:.0f} bytes')
    
    print(f'\nZK-SNARK (simulated):')
    print(f'  Proof generation: {snark_avg[0]:.3f} ms')
    print(f'  Proof verification: {snark_avg[1]:.3f} ms')
    print(f'  Proof size: {snark_avg[2]:.0f} bytes')
    
    print(f'\nPerformance:')
    print(f'  Schnorr is {avg_speedup:.0f}× faster (proof generation)')
    print(f'  Schnorr proofs are {min_ratio:.1f}-{max_ratio:.1f}× smaller')
    print(f'{"="*80}')


if __name__ == "__main__":
    main()
