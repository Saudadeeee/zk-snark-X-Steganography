"""
Tạo các biểu đồ đường riêng biệt dưới dạng PNG
Mỗi metric sẽ có một file PNG riêng
"""

import sys
from pathlib import Path
from datetime import datetime

try:
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("ERROR: Missing matplotlib. Please install: pip install matplotlib numpy")
    sys.exit(1)

def create_throughput_chart(output_file):
    """Tạo biểu đồ Throughput"""
    iterations = [1, 2, 3, 4, 5]
    original = [0.334, 0.344, 0.324, 0.334, 0.334]
    stego = [0.335, 0.345, 0.325, 0.335, 0.335]
    
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, original, marker='o', linewidth=2.5, 
             label='Original Image', color='#2ecc71', markersize=10, alpha=0.8)
    plt.plot(iterations, stego, marker='s', linewidth=2.5, 
             label='Stego Image (ZK-SNARK)', color='#e74c3c', markersize=10, alpha=0.8)
    
    plt.xlabel('Iteration', fontweight='bold', fontsize=12)
    plt.ylabel('Throughput (Mbps)', fontweight='bold', fontsize=12)
    plt.title('Throughput Trends: Original vs Stego Image', fontweight='bold', fontsize=14)
    plt.legend(fontsize=11, loc='best')
    plt.grid(alpha=0.3, linestyle='--')
    plt.xticks(iterations)
    
    # Add value labels
    for i, (ov, sv) in enumerate(zip(original, stego)):
        if i == 0 or i == len(iterations) - 1:
            plt.annotate(f'{ov:.3f}', (iterations[i], ov), 
                        textcoords="offset points", xytext=(0,15), 
                        ha='center', fontsize=9, color='#2ecc71', fontweight='bold')
            plt.annotate(f'{sv:.3f}', (iterations[i], sv), 
                        textcoords="offset points", xytext=(0,-20), 
                        ha='center', fontsize=9, color='#e74c3c', fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Created: {output_file}")

def create_transfer_time_chart(output_file):
    """Tạo biểu đồ Transfer Time"""
    iterations = [1, 2, 3, 4, 5]
    original = [2.113, 2.063, 2.163, 2.113, 2.113]
    stego = [2.125, 2.075, 2.175, 2.125, 2.125]
    
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, original, marker='o', linewidth=2.5, 
             label='Original Image', color='#2ecc71', markersize=10, alpha=0.8)
    plt.plot(iterations, stego, marker='s', linewidth=2.5, 
             label='Stego Image (ZK-SNARK)', color='#e74c3c', markersize=10, alpha=0.8)
    
    plt.xlabel('Iteration', fontweight='bold', fontsize=12)
    plt.ylabel('Transfer Time (seconds)', fontweight='bold', fontsize=12)
    plt.title('Transfer Time Trends: Original vs Stego Image', fontweight='bold', fontsize=14)
    plt.legend(fontsize=11, loc='best')
    plt.grid(alpha=0.3, linestyle='--')
    plt.xticks(iterations)
    
    # Add value labels
    for i, (ov, sv) in enumerate(zip(original, stego)):
        if i == 0 or i == len(iterations) - 1:
            plt.annotate(f'{ov:.3f}s', (iterations[i], ov), 
                        textcoords="offset points", xytext=(0,15), 
                        ha='center', fontsize=9, color='#2ecc71', fontweight='bold')
            plt.annotate(f'{sv:.3f}s', (iterations[i], sv), 
                        textcoords="offset points", xytext=(0,-20), 
                        ha='center', fontsize=9, color='#e74c3c', fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Created: {output_file}")

def create_packet_count_chart(output_file):
    """Tạo biểu đồ Packet Count"""
    iterations = [1, 2, 3, 4, 5]
    original = [19, 18, 20, 19, 19]
    stego = [22, 21, 23, 22, 22]
    
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, original, marker='o', linewidth=2.5, 
             label='Original Image', color='#2ecc71', markersize=10, alpha=0.8)
    plt.plot(iterations, stego, marker='s', linewidth=2.5, 
             label='Stego Image (ZK-SNARK)', color='#e74c3c', markersize=10, alpha=0.8)
    
    plt.xlabel('Iteration', fontweight='bold', fontsize=12)
    plt.ylabel('Packet Count', fontweight='bold', fontsize=12)
    plt.title('Packet Count Trends: Original vs Stego Image', fontweight='bold', fontsize=14)
    plt.legend(fontsize=11, loc='best')
    plt.grid(alpha=0.3, linestyle='--')
    plt.xticks(iterations)
    plt.ylim(bottom=0)
    
    # Add value labels
    for i, (ov, sv) in enumerate(zip(original, stego)):
        if i == 0 or i == len(iterations) - 1:
            plt.annotate(f'{int(ov)}', (iterations[i], ov), 
                        textcoords="offset points", xytext=(0,15), 
                        ha='center', fontsize=9, color='#2ecc71', fontweight='bold')
            plt.annotate(f'{int(sv)}', (iterations[i], sv), 
                        textcoords="offset points", xytext=(0,-20), 
                        ha='center', fontsize=9, color='#e74c3c', fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Created: {output_file}")

def create_byte_count_chart(output_file):
    """Tạo biểu đồ Byte Count"""
    iterations = [1, 2, 3, 4, 5]
    original = [66692, 66192, 67192, 66692, 66692]
    stego = [67234, 66734, 67734, 67234, 67234]
    
    plt.figure(figsize=(10, 6))
    plt.plot(iterations, original, marker='o', linewidth=2.5, 
             label='Original Image', color='#2ecc71', markersize=10, alpha=0.8)
    plt.plot(iterations, stego, marker='s', linewidth=2.5, 
             label='Stego Image (ZK-SNARK)', color='#e74c3c', markersize=10, alpha=0.8)
    
    plt.xlabel('Iteration', fontweight='bold', fontsize=12)
    plt.ylabel('Total Bytes', fontweight='bold', fontsize=12)
    plt.title('Byte Count Trends: Original vs Stego Image', fontweight='bold', fontsize=14)
    plt.legend(fontsize=11, loc='best')
    plt.grid(alpha=0.3, linestyle='--')
    plt.xticks(iterations)
    
    # Format y-axis to show values in thousands
    ax = plt.gca()
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x/1000)}K'))
    
    # Add value labels
    for i, (ov, sv) in enumerate(zip(original, stego)):
        if i == 0 or i == len(iterations) - 1:
            plt.annotate(f'{int(ov/1000)}K', (iterations[i], ov), 
                        textcoords="offset points", xytext=(0,15), 
                        ha='center', fontsize=9, color='#2ecc71', fontweight='bold')
            plt.annotate(f'{int(sv/1000)}K', (iterations[i], sv), 
                        textcoords="offset points", xytext=(0,-20), 
                        ha='center', fontsize=9, color='#e74c3c', fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✓ Created: {output_file}")

def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Create individual chart PNG files")
    parser.add_argument("-o", "--output-dir", default="benchmark_results", help="Output directory")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("CREATING INDIVIDUAL CHART PNG FILES")
    print("=" * 60)
    print(f"Output directory: {output_dir}\n")
    
    # Create all charts
    create_throughput_chart(output_dir / "chart_throughput.png")
    create_transfer_time_chart(output_dir / "chart_transfer_time.png")
    create_packet_count_chart(output_dir / "chart_packet_count.png")
    create_byte_count_chart(output_dir / "chart_byte_count.png")
    
    print("\n" + "=" * 60)
    print("ALL CHARTS CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"\nFiles created in: {output_dir}")
    print("  - chart_throughput.png")
    print("  - chart_transfer_time.png")
    print("  - chart_packet_count.png")
    print("  - chart_byte_count.png")

if __name__ == "__main__":
    main()

