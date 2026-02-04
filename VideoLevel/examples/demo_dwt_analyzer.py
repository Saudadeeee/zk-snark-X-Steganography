"""
DWT Analyzer Demonstration

Shows Haar wavelet transform analysis of macroblocks with visualization.
"""

import numpy as np
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.zk_mv_stego.preprocessing.dwt_analyzer import HaarDWTAnalyzer


def create_test_patterns():
    """Create test macroblocks with different frequency characteristics"""
    
    # Pattern 1: Smooth (low frequency)
    smooth = np.full((16, 16), 128.0, dtype=np.float32)
    
    # Pattern 2: Vertical edges (LH - mid frequency)
    vertical = np.zeros((16, 16), dtype=np.float32)
    vertical[:, :8] = 50
    vertical[:, 8:] = 200
    
    # Pattern 3: Horizontal edges (HL - mid frequency)
    horizontal = np.zeros((16, 16), dtype=np.float32)
    horizontal[:8, :] = 50
    horizontal[8:, :] = 200
    
    # Pattern 4: Checkerboard (HH - high frequency)
    checkerboard = np.zeros((16, 16), dtype=np.float32)
    for i in range(16):
        for j in range(16):
            if (i + j) % 2 == 0:
                checkerboard[i, j] = 200
            else:
                checkerboard[i, j] = 50
    
    # Pattern 5: Gradient (mixed frequencies)
    gradient = np.zeros((16, 16), dtype=np.float32)
    for i in range(16):
        for j in range(16):
            gradient[i, j] = i * 16 + j
    
    return {
        'smooth': smooth,
        'vertical_edges': vertical,
        'horizontal_edges': horizontal,
        'checkerboard': checkerboard,
        'gradient': gradient
    }


def analyze_pattern(analyzer, name, pattern):
    """Analyze a single pattern"""
    print(f"\n{'='*70}")
    print(f"Pattern: {name.upper().replace('_', ' ')}")
    print(f"{'='*70}")
    
    # Perform DWT
    dwt_coeffs = analyzer.analyze_macroblock(pattern)
    
    # Compute energy
    energy_map = analyzer.compute_energy_map(dwt_coeffs)
    
    # Classify
    classification = analyzer.classify_frequency_region(energy_map)
    
    # Get stable regions
    stable = analyzer.get_stable_regions(dwt_coeffs, energy_map, threshold=10.0)
    
    # Display results
    print(f"\n📊 Energy Distribution:")
    for band in ['LL2', 'LH2', 'HL2', 'HH2', 'LH1', 'HL1', 'HH1']:
        energy = energy_map.get(band, 0.0)
        percentage = (energy / energy_map['total'] * 100) if energy_map['total'] > 0 else 0
        bar = '█' * int(percentage / 2)
        print(f"   {band:4s}: {energy:8.2f}  {percentage:5.1f}%  {bar}")
    
    print(f"\n   Total: {energy_map['total']:.2f}")
    
    print(f"\n🎯 Classification: {classification.upper()}")
    
    print(f"\n✅ Stable Regions for Embedding:")
    if stable:
        print(f"   {', '.join(stable)}")
    else:
        print(f"   None (energy too low)")
    
    # Reconstruction test
    reconstructed = analyzer.reconstruct_from_dwt(dwt_coeffs, levels=2)
    mae = np.abs(pattern - reconstructed).mean()
    print(f"\n🔄 Reconstruction MAE: {mae:.6f}")
    
    # Sub-band statistics
    print(f"\n📈 Sub-band Statistics:")
    for band_name, coeffs in dwt_coeffs.items():
        print(f"   {band_name:4s}: shape={coeffs.shape}, "
              f"mean={coeffs.mean():7.2f}, "
              f"std={coeffs.std():7.2f}, "
              f"min={coeffs.min():7.2f}, "
              f"max={coeffs.max():7.2f}")


def test_position_mapping(analyzer):
    """Test DCT coefficient position to DWT region mapping"""
    print(f"\n{'='*70}")
    print(f"DCT POSITION → DWT REGION MAPPING (16x16 Macroblock)")
    print(f"{'='*70}")
    
    # Test key positions
    positions = [
        (0, "Top-left corner (DC)"),
        (7, "Top edge"),
        (8, "Mid-top (crossing to LH)"),
        (63, "LL/LH boundary"),
        (64, "LH region start"),
        (128, "HL region start"),
        (136, "HH region start"),
        (255, "Bottom-right corner")
    ]
    
    print(f"\n{'Position':<10} {'Region':<8} {'Description'}")
    print("-" * 50)
    for pos, desc in positions:
        region = analyzer.get_dwt_region_for_position(pos, 16)
        row = pos // 16
        col = pos % 16
        print(f"{pos:<10} {region:<8} ({row:2d},{col:2d})  {desc}")


def benchmark_performance(analyzer):
    """Benchmark DWT performance on different sizes"""
    print(f"\n{'='*70}")
    print(f"PERFORMANCE BENCHMARK")
    print(f"{'='*70}")
    
    import time
    
    sizes = [8, 16]
    iterations = 10000
    
    for size in sizes:
        mb = np.random.rand(size, size).astype(np.float32) * 255
        
        # Benchmark DWT
        start = time.time()
        for _ in range(iterations):
            dwt_coeffs = analyzer.analyze_macroblock(mb)
        dwt_time = (time.time() - start) / iterations
        
        # Benchmark energy
        start = time.time()
        for _ in range(iterations):
            energy_map = analyzer.compute_energy_map(dwt_coeffs)
        energy_time = (time.time() - start) / iterations
        
        # Benchmark classification
        start = time.time()
        for _ in range(iterations):
            classification = analyzer.classify_frequency_region(energy_map)
        classify_time = (time.time() - start) / iterations
        
        total_time = dwt_time + energy_time + classify_time
        
        print(f"\n{size}x{size} Macroblock ({iterations:,} iterations):")
        print(f"   2-level DWT:      {dwt_time*1000:7.3f} ms  ({1/dwt_time:8.0f} MB/sec)")
        print(f"   Energy map:       {energy_time*1000:7.3f} ms")
        print(f"   Classification:   {classify_time*1000:7.3f} ms")
        print(f"   ─────────────────────────────────")
        print(f"   Total per MB:     {total_time*1000:7.3f} ms  ({1/total_time:8.0f} MB/sec)")
        
        # Estimate video processing speed
        if size == 16:
            # 720p has (1280/16) * (720/16) = 80 * 45 = 3600 macroblocks
            mbs_per_frame_720p = (1280 // 16) * (720 // 16)
            frame_time = total_time * mbs_per_frame_720p
            fps = 1 / frame_time if frame_time > 0 else 0
            
            print(f"\n   📹 720p Processing Estimate:")
            print(f"   Macroblocks per frame: {mbs_per_frame_720p}")
            print(f"   Time per frame:        {frame_time*1000:.1f} ms")
            print(f"   Throughput:            {fps:.1f} fps")


def main():
    print("="*70)
    print(" " * 15 + "DWT ANALYZER DEMONSTRATION")
    print("="*70)
    
    # Initialize analyzer
    analyzer = HaarDWTAnalyzer(levels=2)
    print(f"\n✅ Initialized 2-level Haar DWT Analyzer")
    
    # Create test patterns
    patterns = create_test_patterns()
    
    # Analyze each pattern
    for name, pattern in patterns.items():
        analyze_pattern(analyzer, name, pattern)
    
    # Test position mapping
    test_position_mapping(analyzer)
    
    # Performance benchmark
    benchmark_performance(analyzer)
    
    print(f"\n{'='*70}")
    print("✅ DEMONSTRATION COMPLETE")
    print(f"{'='*70}")
    
    print(f"\nNext steps:")
    print(f"• Week 3: Implement Hybrid Selector (combines DWT + DCT)")
    print(f"• Integrate with existing H.264 parser")
    print(f"• Test on real video macroblocks")


if __name__ == "__main__":
    main()
