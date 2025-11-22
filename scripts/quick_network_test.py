"""
Quick Network Test - Demo script để test nhanh network benchmark
"""

import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from network_benchmark import NetworkBenchmark

def main():
    """Quick test với ảnh mẫu"""
    
    test_image = project_root / "examples" / "testvectors" / "Lenna_test_image.webp"
    
    if not test_image.exists():
        print(f"ERROR: Test image not found: {test_image}")
        print("Please provide an image path as argument")
        if len(sys.argv) > 1:
            test_image = Path(sys.argv[1])
            if not test_image.exists():
                print(f"ERROR: Image not found: {test_image}")
                return 1
        else:
            return 1
    
    print("=" * 60)
    print("QUICK NETWORK BENCHMARK TEST")
    print("=" * 60)
    print(f"Image: {test_image}")
    print("Running 2 iterations for quick test...")
    print("=" * 60)
    
    benchmark = NetworkBenchmark(output_dir="benchmark_results")
    
    try:
        results = benchmark.run_benchmark(
            str(test_image),
            iterations=2
        )
        
        json_file = benchmark.save_results(results)
        
        print("\n" + "=" * 60)
        print("QUICK COMPARISON")
        print("=" * 60)
        df = benchmark.create_comparison_table(results)
        print(df.to_string(index=False))
        
        benchmark.create_plots(results, output_prefix="quick_test")
        
        print("\n" + "=" * 60)
        print("QUICK TEST COMPLETED")
        print("=" * 60)
        print(f"Results: {json_file}")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

