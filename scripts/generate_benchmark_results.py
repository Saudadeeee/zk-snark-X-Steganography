"""
Generate benchmark results với bảng và biểu đồ đường
Sử dụng dữ liệu mẫu để tạo visualization
"""

import json
import sys
from pathlib import Path
from datetime import datetime

try:
    import matplotlib.pyplot as plt
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERROR: Missing matplotlib/pandas. Installing...")
    print("Please run: pip install matplotlib pandas numpy")
    sys.exit(1)

def generate_sample_data(iterations=50):
    """Tạo dữ liệu mẫu dựa trên kết quả thực tế"""
    # Base values từ kết quả thực tế
    orig_base = {
        "file_size": 427806,
        "packets": 19,
        "bytes": 66692,
        "throughput_mbps": 0.334,
        "transfer_time": 2.113
    }
    
    stego_base = {
        "file_size": 429945,  # +0.5% overhead
        "packets": 22,  # Slightly more packets
        "bytes": 67234,  # Slightly more bytes
        "throughput_mbps": 0.335,  # Similar
        "transfer_time": 2.125  # Slightly longer
    }
    
    # Generate iterations with some variance
    np.random.seed(42)
    orig_results = []
    stego_results = []
    
    for i in range(iterations):
        # Add small random variance with slight trend
        trend_factor = np.sin(i * np.pi / iterations) * 0.1  # Slight sinusoidal trend
        orig_results.append({
            "packets": int(orig_base["packets"] + np.random.normal(0, 1) + trend_factor),
            "bytes": int(orig_base["bytes"] + np.random.normal(0, 500) + trend_factor * 100),
            "throughput_mbps": orig_base["throughput_mbps"] + np.random.normal(0, 0.01) + trend_factor * 0.01,
            "transfer_time": orig_base["transfer_time"] + np.random.normal(0, 0.05) - trend_factor * 0.05
        })
        
        stego_results.append({
            "packets": int(stego_base["packets"] + np.random.normal(0, 1) + trend_factor),
            "bytes": int(stego_base["bytes"] + np.random.normal(0, 500) + trend_factor * 100),
            "throughput_mbps": stego_base["throughput_mbps"] + np.random.normal(0, 0.01) + trend_factor * 0.01,
            "transfer_time": stego_base["transfer_time"] + np.random.normal(0, 0.05) - trend_factor * 0.05
        })
    
    return {
        "timestamp": datetime.now().isoformat(),
        "original_image": {
            "file_size": orig_base["file_size"],
            "raw_results": orig_results
        },
        "stego_image": {
            "file_size": stego_base["file_size"],
            "raw_results": stego_results
        }
    }

def create_comparison_table(results):
    """Tạo bảng so sánh"""
    orig = results["original_image"]
    stego = results["stego_image"]
    
    orig_results = orig["raw_results"]
    stego_results = stego["raw_results"]
    
    def calc_stats(values):
        mean = np.mean(values)
        std = np.std(values)
        return mean, std
    
    orig_packets = [r["packets"] for r in orig_results]
    stego_packets = [r["packets"] for r in stego_results]
    orig_bytes = [r["bytes"] for r in orig_results]
    stego_bytes = [r["bytes"] for r in stego_results]
    orig_throughput = [r["throughput_mbps"] for r in orig_results]
    stego_throughput = [r["throughput_mbps"] for r in stego_results]
    orig_time = [r["transfer_time"] for r in orig_results]
    stego_time = [r["transfer_time"] for r in stego_results]
    
    orig_packets_mean, orig_packets_std = calc_stats(orig_packets)
    stego_packets_mean, stego_packets_std = calc_stats(stego_packets)
    orig_bytes_mean, orig_bytes_std = calc_stats(orig_bytes)
    stego_bytes_mean, stego_bytes_std = calc_stats(stego_bytes)
    orig_throughput_mean, orig_throughput_std = calc_stats(orig_throughput)
    stego_throughput_mean, stego_throughput_std = calc_stats(stego_throughput)
    orig_time_mean, orig_time_std = calc_stats(orig_time)
    stego_time_mean, stego_time_std = calc_stats(stego_time)
    
    data = {
        "Metric": [
            "File Size (bytes)",
            "File Size (KB)",
            "Total Packets",
            "Total Bytes",
            "Throughput (Mbps)",
            "Transfer Time (seconds)"
        ],
        "Original Image": [
            f"{orig['file_size']:,}",
            f"{orig['file_size']/1024:.2f}",
            f"{orig_packets_mean:.1f} ± {orig_packets_std:.1f}",
            f"{orig_bytes_mean:.0f} ± {orig_bytes_std:.0f}",
            f"{orig_throughput_mean:.3f} ± {orig_throughput_std:.3f}",
            f"{orig_time_mean:.3f} ± {orig_time_std:.3f}"
        ],
        "Stego Image": [
            f"{stego['file_size']:,}",
            f"{stego['file_size']/1024:.2f}",
            f"{stego_packets_mean:.1f} ± {stego_packets_std:.1f}",
            f"{stego_bytes_mean:.0f} ± {stego_bytes_std:.0f}",
            f"{stego_throughput_mean:.3f} ± {stego_throughput_std:.3f}",
            f"{stego_time_mean:.3f} ± {stego_time_std:.3f}"
        ],
        "Difference": [
            f"{stego['file_size'] - orig['file_size']:+,} bytes",
            f"{((stego['file_size'] - orig['file_size']) / orig['file_size'] * 100):+.2f}%",
            f"{stego_packets_mean - orig_packets_mean:+.1f} ({((stego_packets_mean - orig_packets_mean) / orig_packets_mean * 100):+.2f}%)",
            f"{stego_bytes_mean - orig_bytes_mean:+.0f} ({((stego_bytes_mean - orig_bytes_mean) / orig_bytes_mean * 100):+.2f}%)",
            f"{stego_throughput_mean - orig_throughput_mean:+.3f} Mbps ({((stego_throughput_mean - orig_throughput_mean) / orig_throughput_mean * 100):+.2f}%)",
            f"{stego_time_mean - orig_time_mean:+.3f} s ({((stego_time_mean - orig_time_mean) / orig_time_mean * 100):+.2f}%)"
        ]
    }
    
    df = pd.DataFrame(data)
    return df

def create_line_plots(results, output_file):
    """Tạo biểu đồ đường"""
    orig_results = results["original_image"]["raw_results"]
    stego_results = results["stego_image"]["raw_results"]
    
    iterations = list(range(1, len(orig_results) + 1))
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Network Performance Trends: Original vs Stego Image (ZK-SNARK)', 
                 fontsize=16, fontweight='bold')
    
    metrics = [
        ("Throughput (Mbps)", "throughput_mbps", "Mbps", axes[0, 0]),
        ("Transfer Time (s)", "transfer_time", "seconds", axes[0, 1]),
        ("Total Packets", "packets", "packets", axes[1, 0]),
        ("Total Bytes", "bytes", "bytes", axes[1, 1])
    ]
    
    for title, key, unit, ax in metrics:
        orig_values = [r.get(key, 0) for r in orig_results]
        stego_values = [r.get(key, 0) for r in stego_results]
        
        ax.plot(iterations, orig_values, marker='o', linewidth=2.5, 
               label='Original Image', color='#2ecc71', markersize=10, alpha=0.8)
        ax.plot(iterations, stego_values, marker='s', linewidth=2.5, 
               label='Stego Image (ZK-SNARK)', color='#e74c3c', markersize=10, alpha=0.8)
        
        ax.set_xlabel('Iteration', fontweight='bold', fontsize=11)
        ax.set_ylabel(unit, fontweight='bold', fontsize=11)
        ax.set_title(title, fontweight='bold', fontsize=12)
        ax.legend(fontsize=10, loc='best')
        ax.grid(alpha=0.3, linestyle='--')
        ax.set_xticks(iterations)
        
        # Add value labels for first and last points
        if len(iterations) > 0:
            ax.annotate(f'{orig_values[0]:.3f}', 
                       (iterations[0], orig_values[0]), 
                       textcoords="offset points", xytext=(0,15), 
                       ha='center', fontsize=9, color='#2ecc71', fontweight='bold')
            ax.annotate(f'{stego_values[0]:.3f}', 
                       (iterations[0], stego_values[0]), 
                       textcoords="offset points", xytext=(0,-20), 
                       ha='center', fontsize=9, color='#e74c3c', fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Line chart saved to: {output_file}")
    plt.close()

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate benchmark results with tables and charts")
    parser.add_argument("-i", "--iterations", type=int, default=50, help="Number of iterations (default: 50)")
    parser.add_argument("-o", "--output-dir", default="benchmark_results", help="Output directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 80)
    print("GENERATING BENCHMARK RESULTS")
    print("=" * 80)
    print(f"Iterations: {args.iterations}")
    print(f"Output directory: {output_dir}")
    
    # Generate sample data
    print("\nGenerating sample data...")
    results = generate_sample_data(args.iterations)
    
    # Create comparison table
    print("\nCreating comparison table...")
    df = create_comparison_table(results)
    
    print("\n" + "=" * 80)
    print("COMPARISON TABLE")
    print("=" * 80)
    print(df.to_string(index=False))
    
    # Save table to file
    table_file = output_dir / "comparison_table.txt"
    with open(table_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("NETWORK PERFORMANCE COMPARISON\n")
        f.write("Original Image vs Stego Image (ZK-SNARK)\n")
        f.write("=" * 80 + "\n\n")
        f.write(df.to_string(index=False))
        f.write("\n\n")
        f.write(f"Generated: {results['timestamp']}\n")
    
    print(f"\nTable saved to: {table_file}")
    
    # Create line plots
    print("\nCreating line charts...")
    chart_file = output_dir / "benchmark_line_chart.png"
    create_line_plots(results, chart_file)
    
    # Save JSON
    json_file = output_dir / f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"JSON saved to: {json_file}")
    
    print("\n" + "=" * 80)
    print("RESULTS GENERATED SUCCESSFULLY")
    print("=" * 80)
    print(f"Table: {table_file}")
    print(f"Chart: {chart_file}")
    print(f"JSON: {json_file}")
    print("\nNote: This is sample data. For real results, run:")
    print("  python scripts/full_wireshark_benchmark.py <image_path> --iterations 5")
    print("(Requires: pip install numpy Pillow matplotlib pandas)")

if __name__ == "__main__":
    main()

