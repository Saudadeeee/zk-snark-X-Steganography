#!/usr/bin/env python3
"""
Export Tables as Images
========================

Convert LaTeX-style tables to clean PNG images for easy viewing
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path
import json
import numpy as np

def create_table_image(data, headers, title, filename, output_dir):
    """Create a clean table image from data"""
    
    fig, ax = plt.subplots(figsize=(12, len(data) * 0.6 + 2))
    ax.axis('tight')
    ax.axis('off')
    
    # Create table
    table = ax.table(cellText=data, colLabels=headers, cellLoc='center',
                    loc='center', bbox=[0, 0, 1, 1])
    
    # Style the table
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 2)
    
    # Header styling
    for i in range(len(headers)):
        cell = table[(0, i)]
        cell.set_facecolor('#4472C4')
        cell.set_text_props(weight='bold', color='white')
        cell.set_edgecolor('white')
        cell.set_linewidth(2)
    
    # Data cells styling
    for i in range(1, len(data) + 1):
        for j in range(len(headers)):
            cell = table[(i, j)]
            if i % 2 == 0:
                cell.set_facecolor('#E7E6E6')
            else:
                cell.set_facecolor('white')
            cell.set_edgecolor('#D0D0D0')
            cell.set_linewidth(1)
    
    # Add title
    plt.title(title, fontsize=14, fontweight='bold', pad=20)
    
    # Save
    output_path = Path(output_dir) / filename
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    
    print(f"Table saved: {output_path}")
    return output_path


def main():
    """Generate table images from benchmark results"""
    
    # Load latest results
    results_dir = Path("results/data")
    json_files = sorted(results_dir.glob("benchmark_results_*.json"))
    
    if not json_files:
        print("No results found!")
        return
    
    latest_file = json_files[-1]
    print(f"Loading: {latest_file}")
    
    with open(latest_file, 'r') as f:
        data = json.load(f)
    
    results = data['results']
    results_sorted = sorted(results, key=lambda r: r['message_length'])
    
    output_dir = Path("results/tables_images")
    output_dir.mkdir(exist_ok=True)
    
    print(f"\nGenerating table images...")
    print("="*60)
    
    # Table 1: Performance Metrics
    perf_data = []
    for r in results_sorted:
        perf_data.append([
            r['message_length'],
            f"{r['embedding_time']*1000:.2f}",
            f"{r['extraction_time']*1000:.2f}",
            f"{r['throughput_bps']/1000:.1f}"
        ])
    
    perf_headers = [
        'Message Length\n(chars)',
        'Embedding Time\n(ms)',
        'Extraction Time\n(ms)',
        'Throughput\n(Kbps)'
    ]
    
    create_table_image(
        perf_data,
        perf_headers,
        'Performance Metrics vs. Message Length',
        'performance_table.png',
        output_dir
    )
    
    # Table 2: Quality Metrics
    quality_data = []
    for r in results_sorted:
        quality_data.append([
            r['message_length'],
            f"{r['psnr_value']:.2f}",
            f"{r['ssim_value']:.4f}",
            f"{r['mse_value']:.4f}"
        ])
    
    quality_headers = [
        'Message Length\n(chars)',
        'PSNR\n(dB)',
        'SSIM',
        'MSE'
    ]
    
    create_table_image(
        quality_data,
        quality_headers,
        'Image Quality Metrics vs. Message Length',
        'quality_table.png',
        output_dir
    )
    
    # Table 3: Security Metrics
    security_data = []
    for r in results_sorted:
        detection_risk = "Low" if r['chi_square_pvalue'] > 0.05 else "High"
        security_data.append([
            r['message_length'],
            f"{r['entropy_difference']:.6f}",
            f"{r['chi_square_pvalue']:.4f}",
            detection_risk
        ])
    
    security_headers = [
        'Message Length\n(chars)',
        'Entropy Diff\n(bits)',
        'Chi-square\np-value',
        'Detection\nRisk'
    ]
    
    create_table_image(
        security_data,
        security_headers,
        'Security Metrics vs. Message Length',
        'security_table.png',
        output_dir
    )
    
    # Table 4: Summary Statistics
    message_lengths = [r['message_length'] for r in results_sorted]
    embedding_times = [r['embedding_time']*1000 for r in results_sorted]
    extraction_times = [r['extraction_time']*1000 for r in results_sorted]
    throughputs = [r['throughput_bps']/1000 for r in results_sorted]
    psnr_values = [r['psnr_value'] for r in results_sorted]
    ssim_values = [r['ssim_value'] for r in results_sorted]
    entropy_diffs = [r['entropy_difference'] for r in results_sorted]
    chi_pvalues = [r['chi_square_pvalue'] for r in results_sorted]
    
    summary_data = [
        ['Message Length Range', f"{min(message_lengths)} - {max(message_lengths)} chars", '', ''],
        ['Performance', '', '', ''],
        ['  Embedding Time (mean)', f"{np.mean(embedding_times):.2f} ms", f"std: {np.std(embedding_times):.2f} ms", ''],
        ['  Extraction Time (mean)', f"{np.mean(extraction_times):.2f} ms", f"std: {np.std(extraction_times):.2f} ms", ''],
        ['  Throughput (mean)', f"{np.mean(throughputs):.1f} Kbps", f"max: {max(throughputs):.1f} Kbps", ''],
        ['Quality', '', '', ''],
        ['  PSNR (mean)', f"{np.mean(psnr_values):.2f} dB", f"range: {min(psnr_values):.1f}-{max(psnr_values):.1f} dB", ''],
        ['  SSIM (mean)', f"{np.mean(ssim_values):.4f}", '', ''],
        ['Security', '', '', ''],
        ['  Entropy Diff (mean)', f"{np.mean(entropy_diffs):.6f} bits", f"max: {max(entropy_diffs):.6f} bits", ''],
        ['  Chi-square p (mean)', f"{np.mean(chi_pvalues):.4f}", f"Undetectable: {sum(1 for p in chi_pvalues if p>0.05)}/{len(chi_pvalues)}", ''],
        ['Results', '', '', ''],
        ['  Success Rate', f"{sum(1 for r in results if r['message_integrity'])/len(results)*100:.1f}%", '', ''],
    ]
    
    summary_headers = ['Metric', 'Value', 'Details', '']
    
    create_table_image(
        summary_data,
        summary_headers,
        'Summary Statistics',
        'summary_table.png',
        output_dir
    )
    
    print("="*60)
    print(f"\nAll tables saved to: {output_dir.absolute()}")
    print("\nGenerated files:")
    for img in sorted(output_dir.glob("*.png")):
        print(f"  - {img.name}")


if __name__ == "__main__":
    main()
