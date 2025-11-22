"""
Simple Network Benchmark - Version không cần matplotlib/pandas
Chỉ so sánh file size và metrics cơ bản
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    import numpy as np
    from PIL import Image
    from zk_stego.hybrid_proof_artifact import HybridProofArtifact
    from zk_stego.metadata_message_generator import MetadataMessageGenerator
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}")
    print("Please install: pip install numpy Pillow")
    sys.exit(1)


def format_bytes(size):
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def create_comparison_table(original_size, stego_size, original_stats, stego_stats):
    """Tạo bảng so sánh dạng text"""
    diff_bytes = stego_size - original_size
    diff_percent = (diff_bytes / original_size * 100) if original_size > 0 else 0
    
    # Estimate packets (assuming ~1400 bytes per packet)
    orig_packets = max(1, int(original_size / 1400))
    stego_packets = max(1, int(stego_size / 1400))
    packet_diff = stego_packets - orig_packets
    
    # Estimate transfer time (assuming 10 Mbps)
    orig_time = (original_size * 8) / (10_000_000)
    stego_time = (stego_size * 8) / (10_000_000)
    time_diff = stego_time - orig_time
    
    # Estimate throughput
    orig_throughput = (original_size * 8) / (orig_time * 1_000_000) if orig_time > 0 else 0
    stego_throughput = (stego_size * 8) / (stego_time * 1_000_000) if stego_time > 0 else 0
    
    print("\n" + "=" * 80)
    print("COMPARISON TABLE - Original Image vs Stego Image")
    print("=" * 80)
    print(f"{'Metric':<40} {'Original':<20} {'Stego':<20} {'Difference':<20}")
    print("-" * 80)
    print(f"{'File Size':<40} {format_bytes(original_size):<20} {format_bytes(stego_size):<20} {format_bytes(diff_bytes):+<20}")
    print(f"{'File Size (bytes)':<40} {original_size:,:<20} {stego_size:,:<20} {diff_bytes:+,:<20}")
    print(f"{'Size Difference (%)':<40} {'-':<20} {'-':<20} {diff_percent:+.2f}%")
    print(f"{'Estimated Packets (1400B/pkt)':<40} {orig_packets:<20} {stego_packets:<20} {packet_diff:+<20}")
    print(f"{'Estimated Transfer Time (10Mbps)':<40} {orig_time:.3f}s{'':<15} {stego_time:.3f}s{'':<15} {time_diff:+.3f}s")
    print(f"{'Estimated Throughput (Mbps)':<40} {orig_throughput:.3f}{'':<17} {stego_throughput:.3f}{'':<17} {(stego_throughput-orig_throughput):+.3f}")
    print("=" * 80)
    
    return {
        "original": {
            "size_bytes": original_size,
            "size_formatted": format_bytes(original_size),
            "estimated_packets": orig_packets,
            "estimated_transfer_time": orig_time,
            "estimated_throughput": orig_throughput
        },
        "stego": {
            "size_bytes": stego_size,
            "size_formatted": format_bytes(stego_size),
            "estimated_packets": stego_packets,
            "estimated_transfer_time": stego_time,
            "estimated_throughput": stego_throughput
        },
        "difference": {
            "size_bytes": diff_bytes,
            "size_percent": diff_percent,
            "packets": packet_diff,
            "transfer_time": time_diff,
            "throughput": stego_throughput - orig_throughput
        }
    }


def main():
    """Main function"""
    print("=" * 80)
    print("SIMPLE NETWORK BENCHMARK - ZK-SNARK Steganography")
    print("=" * 80)
    
    # Use test image
    test_image = project_root / "examples" / "testvectors" / "Lenna_test_image.webp"
    
    if not test_image.exists():
        print(f"ERROR: Test image not found: {test_image}")
        if len(sys.argv) > 1:
            test_image = Path(sys.argv[1])
            if not test_image.exists():
                print(f"ERROR: Image not found: {test_image}")
                return 1
        else:
            return 1
    
    print(f"\nImage: {test_image}")
    print("Preparing test images...")
    
    try:
        # Load original image
        original_img = Image.open(test_image)
        original_array = np.array(original_img)
        original_size = os.path.getsize(test_image)
        
        print(f"Original image loaded: {original_array.shape}")
        print(f"Original file size: {format_bytes(original_size)}")
        
        # Generate message
        generator = MetadataMessageGenerator()
        message = generator.auto_generate_metadata_message(
            str(test_image),
            message_type="comprehensive"
        )
        print(f"Generated message length: {len(message)} characters")
        
        # Create stego image
        print("\nCreating stego image with ZK proof...")
        hybrid = HybridProofArtifact()
        stego_image, proof_package = hybrid.embed_with_proof(
            original_array,
            message,
            chaos_key="benchmark_key"
        )
        
        if stego_image is None:
            print("ERROR: Failed to create stego image")
            return 1
        
        # Save stego image temporarily
        output_dir = project_root / "benchmark_results"
        output_dir.mkdir(exist_ok=True)
        
        stego_temp = output_dir / "stego_test.png"
        stego_image.save(stego_temp, "PNG")
        stego_size = os.path.getsize(stego_temp)
        
        print(f"\nStego image created: {stego_size:,} bytes")
        print(f"ZK Proof generated: {proof_package is not None}")
        
        # Create comparison
        results = create_comparison_table(
            original_size, stego_size,
            {}, {}
        )
        
        # Save results
        results["timestamp"] = datetime.now().isoformat()
        results["original_file"] = str(test_image)
        results["stego_file"] = str(stego_temp)
        results["message_length"] = len(message)
        
        json_file = output_dir / f"simple_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to: {json_file}")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"File size increase: {results['difference']['size_percent']:.2f}%")
        print(f"Additional packets: {results['difference']['packets']:+d}")
        print(f"Additional transfer time: {results['difference']['transfer_time']*1000:.2f} ms")
        print("=" * 80)
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

