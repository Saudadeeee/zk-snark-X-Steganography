"""
Hybrid DCT-DWT Coefficient Selector Demo

Demonstrates the complete preprocessing pipeline:
1. YUV color space conversion
2. Haar DWT frequency analysis
3. Hybrid coefficient selection

Shows:
- Selection strategy based on DWT regions
- Stability scoring algorithm
- Comparison of different macroblock patterns
- Performance benchmarks
"""

import numpy as np
import time
from typing import Dict, List, Tuple

from src.zk_mv_stego.preprocessing.yuv_converter import YUVConverter
from src.zk_mv_stego.preprocessing.dwt_analyzer import HaarDWTAnalyzer
from src.zk_mv_stego.preprocessing.hybrid_selector import HybridCoefficientSelector


def create_test_patterns() -> Dict[str, np.ndarray]:
    """Create various test patterns for demonstration"""
    patterns = {}
    
    # 1. Smooth region (LL dominant)
    patterns['smooth'] = np.ones((16, 16, 3), dtype=np.uint8) * 128
    
    # 2. Vertical edge (LH dominant)
    vert_edge = np.zeros((16, 16, 3), dtype=np.uint8)
    vert_edge[:, 8:, :] = 255
    patterns['vertical_edge'] = vert_edge
    
    # 3. Horizontal edge (HL dominant)
    horiz_edge = np.zeros((16, 16, 3), dtype=np.uint8)
    horiz_edge[8:, :, :] = 255
    patterns['horizontal_edge'] = horiz_edge
    
    # 4. Checkerboard (HH dominant)
    checker = np.zeros((16, 16, 3), dtype=np.uint8)
    for i in range(16):
        for j in range(16):
            if (i // 2 + j // 2) % 2:
                checker[i, j, :] = 255
    patterns['checkerboard'] = checker
    
    # 5. Diagonal gradient
    gradient = np.zeros((16, 16, 3), dtype=np.uint8)
    for i in range(16):
        for j in range(16):
            gradient[i, j, :] = (i + j) * 8
    patterns['gradient'] = gradient
    
    # 6. Random texture
    patterns['random'] = np.random.randint(0, 256, (16, 16, 3), dtype=np.uint8)
    
    return patterns


def create_mock_coefficients(strength: str = 'medium') -> List[Tuple[int, int, List[int]]]:
    """
    Create mock DCT coefficients
    
    Args:
        strength: 'weak', 'medium', 'strong'
    """
    if strength == 'weak':
        base_values = [0, 2, 1, -1, 1, 0, 0, 0]
    elif strength == 'medium':
        base_values = [0, 10, 6, -5, 3, 2, 1, 0]
    else:  # strong
        base_values = [0, 25, 18, -15, 10, 8, 5, 3]
    
    # Create coefficients for 4 blocks
    coefficients = []
    for block_idx in range(4):
        # Add some variation
        variation = np.random.randint(-2, 3, len(base_values))
        coeff_list = [b + v for b, v in zip(base_values, variation)]
        coefficients.append((0, block_idx, coeff_list))
    
    return coefficients


def demo_selection_strategy():
    """Demonstrate selection strategy for different patterns"""
    print("\n" + "="*70)
    print("🎯 HYBRID SELECTOR DEMONSTRATION")
    print("="*70)
    
    # Initialize components
    yuv_converter = YUVConverter()
    dwt_analyzer = HaarDWTAnalyzer(levels=2)
    hybrid_selector = HybridCoefficientSelector(dwt_analyzer=dwt_analyzer)
    
    # Create test patterns
    patterns = create_test_patterns()
    
    print("\n📊 SELECTION RESULTS BY PATTERN TYPE\n")
    
    for pattern_name, rgb_pattern in patterns.items():
        print(f"Pattern: {pattern_name.upper()}")
        print("-" * 70)
        
        # Convert to YUV and extract luma
        y, cb, cr = yuv_converter.extract_yuv_from_frame(rgb_pattern)
        
        # Analyze with DWT
        dwt_result = dwt_analyzer.analyze_macroblock(y)
        energy_map = dwt_analyzer.compute_energy_map(dwt_result)
        frequency_class = dwt_analyzer.classify_frequency_region(energy_map)
        
        # Display DWT energy distribution
        print(f"\nDWT Energy Distribution:")
        total_energy = sum(energy_map.values())
        for band, energy in sorted(energy_map.items()):
            percentage = (energy / total_energy * 100) if total_energy > 0 else 0
            bar = "█" * int(percentage / 2)
            print(f"  {band:4s}: {energy:10.2f} ({percentage:5.1f}%) {bar}")
        
        print(f"\nFrequency Classification: {frequency_class}")
        
        # Test coefficient selection with different strengths
        for strength in ['weak', 'medium', 'strong']:
            coefficients = create_mock_coefficients(strength)
            
            selected = hybrid_selector.select_coefficients(
                coefficients=coefficients,
                macroblock_data=y,
                min_magnitude=2,
                max_coefficients=10
            )
            
            # Create coefficient map
            coeff_map = hybrid_selector.create_coefficient_map(coefficients, y)
            capacity = hybrid_selector.estimate_capacity(coeff_map)
            
            print(f"\nCoefficient Strength: {strength.upper()}")
            print(f"  Selected: {len(selected)} coefficients (max=10)")
            print(f"  Capacity: {capacity} bits")
            
            # Show top 3 selections with scores
            if len(selected) > 0:
                print(f"  Top selections (mb_idx, block_idx, position):")
                for i, (mb_idx, block_idx, position) in enumerate(selected[:3]):
                    # Get the coefficient value
                    coeff_value = coefficients[block_idx][2][position]
                    
                    # Get DWT region
                    dwt_region = dwt_analyzer.get_dwt_region_for_position(position)
                    
                    # Compute score
                    score = hybrid_selector.compute_stability_score(
                        coeff_value, position, dwt_region
                    )
                    
                    print(f"    {i+1}. ({mb_idx}, {block_idx}, {position}) "
                          f"value={coeff_value:3d} region={dwt_region} score={score:.3f}")
        
        print("\n" + "="*70 + "\n")


def demo_selection_rules():
    """Demonstrate the 6 selection rules"""
    print("\n" + "="*70)
    print("📋 SELECTION RULES DEMONSTRATION")
    print("="*70)
    
    hybrid_selector = HybridCoefficientSelector()
    
    # Create test macroblock (textured)
    macroblock = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    
    print("\nTesting each rule:\n")
    
    test_cases = [
        # (value, position, dwt_region, texture, description, expected)
        (100, 0, 'LH', 1.0, "Rule 1: DC coefficient (position 0)", False),
        (100, 5, 'HH', 1.0, "Rule 2: High frequency (HH region)", False),
        (1, 5, 'LH', 1.0, "Rule 3: Small coefficient (|value| < 2)", False),
        (10, 5, 'LH', 0.2, "Rule 4: Low texture (< 0.3)", False),
        (5, 5, 'LH', 0.5, "Rule 5: Mid-freq edge (LH, |value| >= 3)", True),
        (6, 5, 'LL', 0.5, "Rule 6: Smooth region (LL, |value| >= 5)", True),
    ]
    
    for i, (value, pos, region, texture, desc, expected) in enumerate(test_cases, 1):
        result = hybrid_selector.should_use_coefficient(value, pos, region, texture)
        status = "✅ ACCEPT" if result else "❌ REJECT"
        match = "✓" if result == expected else "✗"
        
        print(f"{i}. {desc}")
        print(f"   Input: value={value}, pos={pos}, region={region}, texture={texture}")
        print(f"   Result: {status} {match}")
        print()


def demo_stability_scoring():
    """Demonstrate stability scoring algorithm"""
    print("\n" + "="*70)
    print("📈 STABILITY SCORING DEMONSTRATION")
    print("="*70)
    
    hybrid_selector = HybridCoefficientSelector()
    
    print("\nScore = log(|coeff| + 1) / log(256) × region_weight × context_score")
    print("Context = 0.6×texture + 0.4×motion\n")
    
    print("Magnitude Impact (region=LH, texture=1.0, motion=0.0):")
    print("-" * 70)
    for magnitude in [2, 5, 10, 20, 50, 100, 200]:
        score = hybrid_selector.compute_stability_score(magnitude, 5, 'LH', 1.0, 0.0)
        bar = "█" * int(score * 50)
        print(f"  |value| = {magnitude:3d}: score = {score:.4f} {bar}")
    
    print("\nRegion Weight Impact (|value|=50, texture=1.0, motion=0.0):")
    print("-" * 70)
    for region in ['LH', 'HL', 'LL', 'HH']:
        score = hybrid_selector.compute_stability_score(50, 5, region, 1.0, 0.0)
        weight = hybrid_selector.region_weights[region]
        bar = "█" * int(score * 50)
        print(f"  Region {region}: weight={weight:.1f} score={score:.4f} {bar}")
    
    print("\nTexture Impact (|value|=50, region=LH, motion=0.0):")
    print("-" * 70)
    for texture in [0.0, 0.3, 0.5, 0.7, 1.0]:
        score = hybrid_selector.compute_stability_score(50, 5, 'LH', texture, 0.0)
        bar = "█" * int(score * 50)
        print(f"  Texture = {texture:.1f}: score = {score:.4f} {bar}")


def demo_performance_benchmark():
    """Benchmark the complete pipeline"""
    print("\n" + "="*70)
    print("⚡ PERFORMANCE BENCHMARK")
    print("="*70)
    
    yuv_converter = YUVConverter()
    dwt_analyzer = HaarDWTAnalyzer(levels=2)
    hybrid_selector = HybridCoefficientSelector(dwt_analyzer=dwt_analyzer)
    
    # Create test data
    rgb_macroblock = np.random.randint(0, 256, (16, 16, 3), dtype=np.uint8)
    mock_coefficients = [
        (0, i, [0, 15, 10, -8, 6, 4, 2, 1])
        for i in range(16)  # 16 4x4 blocks
    ]
    
    print("\nRunning 10,000 iterations...\n")
    
    iterations = 10000
    
    # Benchmark each component
    times = {}
    
    # 1. YUV conversion
    start = time.perf_counter()
    for _ in range(iterations):
        y, cb, cr = yuv_converter.extract_yuv_from_frame(rgb_macroblock)
    times['YUV'] = (time.perf_counter() - start) * 1000 / iterations
    
    # 2. DWT analysis
    y, cb, cr = yuv_converter.extract_yuv_from_frame(rgb_macroblock)
    start = time.perf_counter()
    for _ in range(iterations):
        dwt_result = dwt_analyzer.analyze_macroblock(y)
    times['DWT'] = (time.perf_counter() - start) * 1000 / iterations
    
    # 3. Energy computation
    dwt_result = dwt_analyzer.analyze_macroblock(y)
    start = time.perf_counter()
    for _ in range(iterations):
        energy_map = dwt_analyzer.compute_energy_map(dwt_result)
    times['Energy'] = (time.perf_counter() - start) * 1000 / iterations
    
    # 4. Hybrid selection
    start = time.perf_counter()
    for _ in range(iterations):
        selected = hybrid_selector.select_coefficients(
            mock_coefficients, y, min_magnitude=2, max_coefficients=10
        )
    times['Selection'] = (time.perf_counter() - start) * 1000 / iterations
    
    # 5. Full pipeline
    start = time.perf_counter()
    for _ in range(iterations):
        y, cb, cr = yuv_converter.extract_yuv_from_frame(rgb_macroblock)
        dwt_result = dwt_analyzer.analyze_macroblock(y)
        energy_map = dwt_analyzer.compute_energy_map(dwt_result)
        selected = hybrid_selector.select_coefficients(
            mock_coefficients, y, min_magnitude=2, max_coefficients=10
        )
    times['Full Pipeline'] = (time.perf_counter() - start) * 1000 / iterations
    
    # Display results
    print("Component Performance (per 16×16 macroblock):")
    print("-" * 70)
    for component, time_ms in times.items():
        throughput_mb_sec = 1000 / time_ms if time_ms > 0 else 0
        bar = "█" * int(min(time_ms * 10, 50))
        print(f"  {component:15s}: {time_ms:6.3f} ms  ({throughput_mb_sec:7.0f} MB/sec) {bar}")
    
    # Video processing estimates
    print("\n720p Video Processing Estimates (1280×720, 3600 MBs/frame):")
    print("-" * 70)
    full_time = times['Full Pipeline']
    frame_time_ms = full_time * 3600
    fps = 1000 / frame_time_ms if frame_time_ms > 0 else 0
    print(f"  Time per frame: {frame_time_ms:.1f} ms")
    print(f"  Throughput: {fps:.1f} fps")
    
    print("\n1080p Video Processing Estimates (1920×1080, 8100 MBs/frame):")
    print("-" * 70)
    frame_time_ms = full_time * 8100
    fps = 1000 / frame_time_ms if frame_time_ms > 0 else 0
    print(f"  Time per frame: {frame_time_ms:.1f} ms")
    print(f"  Throughput: {fps:.1f} fps")


def main():
    """Run all demonstrations"""
    print("\n" + "█"*70)
    print("█" + " "*68 + "█")
    print("█" + "  HYBRID DCT-DWT COEFFICIENT SELECTOR - DEMO".center(68) + "█")
    print("█" + "  Week 3: Phase 1 Preprocessing Pipeline".center(68) + "█")
    print("█" + " "*68 + "█")
    print("█"*70)
    
    # Run demonstrations
    demo_selection_strategy()
    demo_selection_rules()
    demo_stability_scoring()
    demo_performance_benchmark()
    
    print("\n" + "="*70)
    print("✅ DEMO COMPLETE")
    print("="*70)
    print("\nNext Steps:")
    print("  1. Integration with H.264 parser (Week 2 Day 6-7)")
    print("  2. Benchmark vs v2.0 selection (Week 3 Day 6-7)")
    print("  3. Test on real video samples (data/raw/*.h264)")
    print("  4. Update payload_embedder.py to use hybrid selector")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
