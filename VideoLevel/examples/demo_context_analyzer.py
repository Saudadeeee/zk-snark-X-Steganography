"""
Context Analyzer Demonstration

Shows:
1. Texture analysis (smooth vs textured blocks)
2. Motion analysis (static vs moving blocks)
3. Context scoring and classification
4. Frame-level analysis
5. Integration with hybrid selector
6. Visual comparison
"""

import numpy as np
import matplotlib.pyplot as plt
from src.zk_mv_stego.preprocessing.context_analyzer import ContextAnalyzer
from src.zk_mv_stego.preprocessing.hybrid_selector import HybridCoefficientSelector
import time


def create_test_macroblocks() -> dict:
    """Create test macroblocks with different characteristics"""
    blocks = {}
    
    # 1. Smooth block (constant gray)
    blocks['smooth'] = np.ones((16, 16), dtype=np.uint8) * 128
    
    # 2. Textured block (checkerboard)
    textured = np.zeros((16, 16), dtype=np.uint8)
    textured[::2, ::2] = 255
    textured[1::2, 1::2] = 255
    blocks['textured'] = textured
    
    # 3. Edge block (vertical edge)
    edge = np.zeros((16, 16), dtype=np.uint8)
    edge[:, 8:] = 255
    blocks['edge'] = edge
    
    # 4. Random noise
    blocks['noise'] = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    
    # 5. Gradient
    gradient = np.zeros((16, 16), dtype=np.uint8)
    for i in range(16):
        gradient[i, :] = int(i * 255 / 15)
    blocks['gradient'] = gradient
    
    # 6. Natural texture (simulate)
    natural = np.random.randint(100, 156, (16, 16), dtype=np.int16)
    natural[4:12, 4:12] += np.random.randint(-30, 30, (8, 8), dtype=np.int16)
    blocks['natural'] = np.clip(natural, 0, 255).astype(np.uint8)
    
    return blocks


def demo_texture_analysis():
    """Demo 1: Texture analysis comparison"""
    print("=" * 70)
    print("DEMO 1: Texture Analysis")
    print("=" * 70)
    
    analyzer = ContextAnalyzer()
    blocks = create_test_macroblocks()
    
    print(f"{'Block Type':<15} {'Laplacian':<12} {'Std Dev':<12} {'Combined':<12}")
    print("-" * 70)
    
    results = {}
    for name, block in blocks.items():
        lap_score = analyzer.analyze_texture(block, method='laplacian')
        std_score = analyzer.analyze_texture(block, method='std')
        combined = analyzer.analyze_texture(block, method='combined')
        
        results[name] = {
            'laplacian': lap_score,
            'std': std_score,
            'combined': combined,
            'block': block
        }
        
        print(f"{name:<15} {lap_score:>10.4f}  {std_score:>10.4f}  {combined:>10.4f}")
    
    # Visualize blocks and scores
    fig, axes = plt.subplots(2, 6, figsize=(18, 6))
    
    for idx, (name, data) in enumerate(results.items()):
        # Show block
        axes[0, idx].imshow(data['block'], cmap='gray', vmin=0, vmax=255)
        axes[0, idx].set_title(name.capitalize())
        axes[0, idx].axis('off')
        
        # Show scores
        methods = ['laplacian', 'std', 'combined']
        scores = [data[m] for m in methods]
        colors = ['steelblue', 'forestgreen', 'orange']
        
        bars = axes[1, idx].bar(range(3), scores, color=colors, alpha=0.7)
        axes[1, idx].set_ylim(0, 1.0)
        axes[1, idx].set_xticks(range(3))
        axes[1, idx].set_xticklabels(['Lap', 'Std', 'Comb'], fontsize=8)
        axes[1, idx].set_ylabel('Score', fontsize=8)
        axes[1, idx].grid(axis='y', alpha=0.3)
        
        # Add value labels
        for bar, score in zip(bars, scores):
            axes[1, idx].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                            f'{score:.2f}', ha='center', va='bottom', fontsize=7)
    
    plt.tight_layout()
    plt.savefig('data/output/context_texture_analysis.png', dpi=150, bbox_inches='tight')
    print(f"\n✓ Visualization saved: data/output/context_texture_analysis.png")
    print()


def demo_motion_analysis():
    """Demo 2: Motion analysis with optical flow"""
    print("=" * 70)
    print("DEMO 2: Motion Analysis")
    print("=" * 70)
    
    analyzer = ContextAnalyzer()
    
    # Create static and moving scenarios
    scenarios = {}
    
    # 1. Static block (no motion)
    prev_static = np.ones((16, 16), dtype=np.uint8) * 128
    curr_static = np.ones((16, 16), dtype=np.uint8) * 128
    scenarios['static'] = (curr_static, prev_static)
    
    # 2. Small motion (shifted by 2 pixels)
    prev_small = np.zeros((16, 16), dtype=np.uint8)
    prev_small[4:12, 4:12] = 255
    curr_small = np.zeros((16, 16), dtype=np.uint8)
    curr_small[6:14, 6:14] = 255
    scenarios['small_motion'] = (curr_small, prev_small)
    
    # 3. Large motion (motion vector)
    curr_large = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    scenarios['large_motion_mv'] = (curr_large, None, (15.0, 15.0))
    
    # 4. Random change (different random patterns)
    curr_random = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    prev_random = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    scenarios['random'] = (curr_random, prev_random)
    
    print(f"{'Scenario':<20} {'Method':<15} {'Motion Score':<12}")
    print("-" * 70)
    
    for name, data in scenarios.items():
        if len(data) == 3:
            curr, prev, mv = data
            score = analyzer.analyze_motion(curr, previous_mb=prev, motion_vector=mv)
            method = "Motion Vector"
        else:
            curr, prev = data
            score = analyzer.analyze_motion(curr, previous_mb=prev)
            method = "Optical Flow"
        
        print(f"{name:<20} {method:<15} {score:>10.4f}")
    
    print()


def demo_context_scoring():
    """Demo 3: Context scoring and classification"""
    print("=" * 70)
    print("DEMO 3: Context Scoring and Classification")
    print("=" * 70)
    
    analyzer = ContextAnalyzer()
    blocks = create_test_macroblocks()
    
    print(f"{'Block Type':<15} {'Texture':<10} {'Motion':<10} {'Context':<10} {'Class':<18} {'Quality':<10}")
    print("-" * 95)
    
    results = []
    for name, block in blocks.items():
        suitability = analyzer.get_embedding_suitability(block)
        
        results.append({
            'name': name,
            **suitability
        })
        
        print(f"{name:<15} "
              f"{suitability['texture_score']:>8.3f}  "
              f"{suitability['motion_score']:>8.3f}  "
              f"{suitability['context_score']:>8.3f}  "
              f"{suitability['classification']:<18} "
              f"{suitability['embedding_quality']:<10}")
    
    # Create classification chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Score comparison
    names = [r['name'] for r in results]
    texture_scores = [r['texture_score'] for r in results]
    motion_scores = [r['motion_score'] for r in results]
    context_scores = [r['context_score'] for r in results]
    
    x = np.arange(len(names))
    width = 0.25
    
    ax1.bar(x - width, texture_scores, width, label='Texture', color='steelblue', alpha=0.8)
    ax1.bar(x, motion_scores, width, label='Motion', color='forestgreen', alpha=0.8)
    ax1.bar(x + width, context_scores, width, label='Context', color='orange', alpha=0.8)
    
    ax1.set_ylabel('Score')
    ax1.set_title('Context Scoring Breakdown')
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=45, ha='right')
    ax1.legend()
    ax1.set_ylim(0, 1.0)
    ax1.grid(axis='y', alpha=0.3)
    
    # Quality distribution
    qualities = [r['embedding_quality'] for r in results]
    quality_counts = {}
    for q in ['poor', 'fair', 'good', 'excellent']:
        quality_counts[q] = qualities.count(q)
    
    colors = {'poor': 'red', 'fair': 'orange', 'good': 'lightgreen', 'excellent': 'green'}
    bars = ax2.bar(quality_counts.keys(), quality_counts.values(),
                   color=[colors[q] for q in quality_counts.keys()], alpha=0.7)
    
    ax2.set_ylabel('Count')
    ax2.set_title('Embedding Quality Distribution')
    ax2.grid(axis='y', alpha=0.3)
    
    # Add count labels
    for bar in bars:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}', ha='center', va='bottom')
    
    plt.tight_layout()
    plt.savefig('data/output/context_scoring.png', dpi=150, bbox_inches='tight')
    print(f"\n✓ Visualization saved: data/output/context_scoring.png")
    print()


def demo_frame_analysis():
    """Demo 4: Full frame analysis"""
    print("=" * 70)
    print("DEMO 4: Frame Analysis (32x32 frame)")
    print("=" * 70)
    
    analyzer = ContextAnalyzer()
    
    # Create 32x32 frame with different regions
    frame = np.zeros((32, 32), dtype=np.uint8)
    frame[:16, :16] = 200  # Smooth top-left
    frame[:16, 16:] = np.random.randint(0, 256, (16, 16))  # Textured top-right
    frame[16:, :16] = 100  # Smooth bottom-left
    frame[16:, 16:] = np.random.randint(100, 156, (16, 16))  # Medium texture bottom-right
    
    # Analyze frame
    results = analyzer.analyze_frame(frame)
    
    print(f"Total macroblocks: {len(results)}")
    print(f"\n{'MB Index':<10} {'Texture':<10} {'Context':<10} {'Quality':<12}")
    print("-" * 50)
    
    for mb_idx in sorted(results.keys()):
        data = results[mb_idx]
        print(f"{mb_idx:<10} "
              f"{data['texture_score']:>8.3f}  "
              f"{data['context_score']:>8.3f}  "
              f"{data['embedding_quality']:<12}")
    
    # Get best macroblocks
    best = analyzer.get_best_macroblocks(results, top_n=2, min_quality='fair')
    print(f"\nBest macroblocks for embedding: {best}")
    
    # Visualize frame analysis
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    # Original frame
    axes[0].imshow(frame, cmap='gray', vmin=0, vmax=255)
    axes[0].set_title('Original Frame (32x32)')
    axes[0].grid(True, color='red', linewidth=0.5)
    axes[0].set_xticks(np.arange(0, 33, 16))
    axes[0].set_yticks(np.arange(0, 33, 16))
    
    # Context score heatmap
    score_map = np.zeros((2, 2))
    for mb_idx, data in results.items():
        row = mb_idx // 2
        col = mb_idx % 2
        score_map[row, col] = data['context_score']
    
    im = axes[1].imshow(score_map, cmap='RdYlGn', vmin=0, vmax=1.0)
    axes[1].set_title('Context Score Heatmap')
    axes[1].set_xticks([0, 1])
    axes[1].set_yticks([0, 1])
    axes[1].set_xticklabels(['Left', 'Right'])
    axes[1].set_yticklabels(['Top', 'Bottom'])
    plt.colorbar(im, ax=axes[1])
    
    # Add score values
    for i in range(2):
        for j in range(2):
            axes[1].text(j, i, f'{score_map[i, j]:.2f}',
                        ha='center', va='center', color='black', fontsize=12)
    
    # Quality classification
    quality_map = np.zeros((2, 2))
    quality_to_num = {'poor': 0, 'fair': 1, 'good': 2, 'excellent': 3}
    for mb_idx, data in results.items():
        row = mb_idx // 2
        col = mb_idx % 2
        quality_map[row, col] = quality_to_num[data['embedding_quality']]
    
    im2 = axes[2].imshow(quality_map, cmap='RdYlGn', vmin=0, vmax=3)
    axes[2].set_title('Embedding Quality Map')
    axes[2].set_xticks([0, 1])
    axes[2].set_yticks([0, 1])
    axes[2].set_xticklabels(['Left', 'Right'])
    axes[2].set_yticklabels(['Top', 'Bottom'])
    
    # Add quality labels
    num_to_quality = {v: k for k, v in quality_to_num.items()}
    for i in range(2):
        for j in range(2):
            quality = num_to_quality[quality_map[i, j]]
            axes[2].text(j, i, quality,
                        ha='center', va='center', color='black', fontsize=10)
    
    plt.tight_layout()
    plt.savefig('data/output/context_frame_analysis.png', dpi=150, bbox_inches='tight')
    print(f"\n✓ Visualization saved: data/output/context_frame_analysis.png")
    print()


def demo_hybrid_integration():
    """Demo 5: Integration with Hybrid Selector"""
    print("=" * 70)
    print("DEMO 5: Hybrid Selector Integration")
    print("=" * 70)
    
    # Create selector with context analyzer
    selector = HybridCoefficientSelector()
    
    # Create test macroblock (textured)
    textured = np.zeros((16, 16), dtype=np.uint8)
    textured[::2, ::2] = 255
    textured[1::2, 1::2] = 255
    
    # Create smooth macroblock
    smooth = np.ones((16, 16), dtype=np.uint8) * 128
    
    # Mock coefficients
    coeffs_textured = [(0, 0, [0, 5, -3, 4, 2, -6, 3])]
    coeffs_smooth = [(0, 0, [0, 2, -2, 1, -1, 2])]
    
    # Select with context (textured block - high score)
    selected_textured = selector.select_coefficients(
        coeffs_textured,
        textured,
        min_magnitude=2
    )
    
    # Select with context (smooth block - low score)
    selected_smooth = selector.select_coefficients(
        coeffs_smooth,
        smooth,
        min_magnitude=2
    )
    
    print("Textured Block:")
    print(f"  Coefficients available: {len(coeffs_textured[0][2])}")
    print(f"  Coefficients selected: {len(selected_textured)}")
    
    print("\nSmooth Block:")
    print(f"  Coefficients available: {len(coeffs_smooth[0][2])}")
    print(f"  Coefficients selected: {len(selected_smooth)}")
    
    print("\nConclusion:")
    print("  Context analyzer helps select from high-texture regions,")
    print("  improving embedding quality and resistance to detection.")
    print()


def demo_performance_benchmark():
    """Demo 6: Performance benchmarking"""
    print("=" * 70)
    print("DEMO 6: Performance Benchmark")
    print("=" * 70)
    
    analyzer = ContextAnalyzer()
    
    # Test different operations
    test_block = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    prev_block = np.random.randint(0, 256, (16, 16), dtype=np.uint8)
    
    iterations = 1000
    
    # Benchmark texture analysis
    start = time.perf_counter()
    for _ in range(iterations):
        _ = analyzer.analyze_texture(test_block, method='laplacian')
    elapsed = time.perf_counter() - start
    texture_time = (elapsed / iterations) * 1000
    
    # Benchmark motion analysis
    start = time.perf_counter()
    for _ in range(iterations):
        _ = analyzer.analyze_motion(test_block, previous_mb=prev_block)
    elapsed = time.perf_counter() - start
    motion_time = (elapsed / iterations) * 1000
    
    # Benchmark full suitability
    start = time.perf_counter()
    for _ in range(iterations):
        _ = analyzer.get_embedding_suitability(test_block, previous_mb=prev_block)
    elapsed = time.perf_counter() - start
    suitability_time = (elapsed / iterations) * 1000
    
    print(f"{'Operation':<25} {'Time (ms)':<12} {'Throughput':<15}")
    print("-" * 60)
    print(f"{'Texture analysis':<25} {texture_time:>10.3f}  {1000/texture_time:>12.1f} ops/sec")
    print(f"{'Motion analysis':<25} {motion_time:>10.3f}  {1000/motion_time:>12.1f} ops/sec")
    print(f"{'Full suitability':<25} {suitability_time:>10.3f}  {1000/suitability_time:>12.1f} ops/sec")
    
    # Estimate frame overhead
    num_mbs_720p = (1280 // 16) * (720 // 16)
    overhead_720p = suitability_time * num_mbs_720p
    
    print(f"\nFrame overhead (720p, {num_mbs_720p} MBs): {overhead_720p:.1f} ms")
    print()


def main():
    """Run all context analyzer demonstrations"""
    print("\n" + "=" * 70)
    print(" CONTEXT ANALYZER DEMONSTRATION")
    print(" For ZK-SNARK Video Steganography v3.0 - Week 5")
    print("=" * 70)
    print()
    
    # Run demos
    demo_texture_analysis()
    demo_motion_analysis()
    demo_context_scoring()
    demo_frame_analysis()
    demo_hybrid_integration()
    demo_performance_benchmark()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("✓ Texture analysis identifies smooth vs textured regions")
    print("✓ Motion analysis detects static vs moving blocks")
    print("✓ Context scoring combines texture + motion (weighted)")
    print("✓ Region classification: high/medium/low/smooth-static")
    print("✓ Frame analysis selects best macroblocks for embedding")
    print("✓ Hybrid selector integration improves coefficient selection")
    print()
    print("Benefits:")
    print("  • Better embedding quality (prefer high-texture/motion)")
    print("  • Lower detection risk (avoid smooth/static regions)")
    print("  • Adaptive selection (context-aware coefficient scoring)")
    print()
    print("Next: Week 6 - LDPC Error Correction")
    print("=" * 70)


if __name__ == '__main__':
    main()
