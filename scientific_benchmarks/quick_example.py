#!/usr/bin/env python3
"""
Quick Example - Scientific Benchmark Suite
===========================================

Minimal example showing how to use the benchmark suite for a single test.
Perfect for learning and quick verification.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))

from scientific_benchmark_suite import ScientificBenchmarkSuite


def main():
    print("="*70)
    print("QUICK EXAMPLE - Scientific Benchmark")
    print("="*70)
    print()
    
    # Initialize benchmark suite
    print("Initializing benchmark suite...")
    suite = ScientificBenchmarkSuite()
    
    # Find a test image
    test_images = list(suite.test_images_dir.glob("*.png")) + \
                  list(suite.test_images_dir.glob("*.webp"))
    
    if not test_images:
        print("ERROR: No test images found in examples/testvectors/")
        print("Please add at least one test image to run benchmarks.")
        return
    
    test_image = test_images[0]
    print(f"Using test image: {test_image.name}")
    print()
    
    # Run single benchmark
    print("Running benchmark...")
    test_message = "This is a test message for scientific benchmarking."
    
    result = suite.run_single_benchmark(
        image_path=test_image,
        message=test_message,
        message_type="example",
        test_id="quick_example_001"
    )
    
    # Display results
    print()
    print("="*70)
    print("RESULTS SUMMARY")
    print("="*70)
    print()
    
    print("📊 Performance Metrics:")
    print(f"   Embedding Time:    {result.embedding_time * 1000:.3f} ms")
    print(f"   Extraction Time:   {result.extraction_time * 1000:.3f} ms")
    print(f"   Throughput:        {result.throughput_bps / 1000:.2f} Kbps")
    print()
    
    print("🎨 Quality Metrics:")
    print(f"   PSNR:              {result.psnr_value:.2f} dB")
    print(f"   SSIM:              {result.ssim_value:.4f}")
    print(f"   MSE:               {result.mse_value:.4f}")
    print()
    
    print("🔒 Security Metrics:")
    print(f"   Entropy (Original): {result.entropy_original:.4f} bits")
    print(f"   Entropy (Stego):    {result.entropy_stego:.4f} bits")
    print(f"   Entropy Δ:          {result.entropy_difference:.6f} bits")
    print(f"   Chi-square p-value: {result.chi_square_pvalue:.4f}")
    print()
    
    print("💾 Capacity Metrics:")
    print(f"   Embedding Rate:     {result.embedding_rate:.4f} bpp")
    print(f"   Capacity Used:      {result.capacity_utilization:.2f}%")
    print()
    
    print("✅ Status:")
    print(f"   Embedding:          {'SUCCESS' if result.embedding_success else 'FAILED'}")
    print(f"   Extraction:         {'SUCCESS' if result.extraction_success else 'FAILED'}")
    print(f"   Message Integrity:  {'VERIFIED' if result.message_integrity else 'CORRUPTED'}")
    print()
    
    # Quality assessment
    print("📝 Assessment:")
    if result.psnr_value > 40:
        print("   ✓ Image quality: EXCELLENT (imperceptible changes)")
    elif result.psnr_value > 30:
        print("   ✓ Image quality: GOOD")
    else:
        print("   ⚠ Image quality: Needs improvement")
    
    if result.chi_square_pvalue > 0.05:
        print("   ✓ Security: HIGH (statistically undetectable)")
    else:
        print("   ⚠ Security: Statistical anomaly detected")
    
    if result.embedding_time < 0.01:
        print("   ✓ Performance: EXCELLENT (< 10 ms)")
    elif result.embedding_time < 0.1:
        print("   ✓ Performance: GOOD (< 100 ms)")
    else:
        print("   ⚠ Performance: Could be optimized")
    
    print()
    print("="*70)
    
    # Save results
    print()
    print("Saving results...")
    suite.save_results_json()
    
    print()
    print("✅ Example completed successfully!")
    print()
    print("Next steps:")
    print("  1. Run full benchmark: python3 scientific_benchmark_suite.py")
    print("  2. View results in: scientific_benchmarks/results/")
    print("  3. Check LaTeX tables for publication")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
