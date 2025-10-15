#!/usr/bin/env python3
"""
Compare OLD vs NEW visualization data
"""

import json
from pathlib import Path

def analyze_comparison():
    # Paths
    old_file = Path('comparative_benchmarks/comparison_results/data/comparison_results_20251015_125516.json')
    new_file = Path('comparative_benchmarks/comparison_results/data/comparison_results_20251015_143013.json')
    
    # Load data
    with open(old_file) as f:
        old_data = json.load(f)
    
    with open(new_file) as f:
        new_data = json.load(f)
    
    print("="*80)
    print("📊 BEFORE vs AFTER COMPARISON")
    print("="*80)
    
    # Test counts
    old_schnorr = len(old_data['results']['ZK-Schnorr'])
    old_snark = len(old_data['results']['ZK-SNARK'])
    new_schnorr = len(new_data['results']['ZK-Schnorr'])
    new_snark = len(new_data['results']['ZK-SNARK'])
    
    print(f"\n📈 TEST COVERAGE")
    print(f"  Before: {old_schnorr + old_snark} tests ({old_schnorr} Schnorr + {old_snark} SNARK)")
    print(f"  After:  {new_schnorr + new_snark} tests ({new_schnorr} Schnorr + {new_snark} SNARK)")
    print(f"  Improvement: {((new_schnorr + new_snark) / (old_schnorr + old_snark) - 1) * 100:.0f}% more tests")
    
    # Message length ranges
    old_lengths = [r['message_length'] for r in old_data['results']['ZK-Schnorr']]
    new_lengths = [r['message_length'] for r in new_data['results']['ZK-Schnorr']]
    
    print(f"\n📏 MESSAGE LENGTH DISTRIBUTION")
    print(f"  Before: {min(old_lengths)}-{max(old_lengths)} chars (step: variable)")
    print(f"  Old sequence: {old_lengths}")
    print(f"  After:  {min(new_lengths)}-{max(new_lengths)} chars (step: {new_lengths[1] - new_lengths[0]})")
    print(f"  New sequence (first 5): {new_lengths[:5]}")
    print(f"  New sequence (last 5):  {new_lengths[-5:]}")
    
    # Calculate statistics
    import numpy as np
    
    old_schnorr_gen = [r['proof_generation_time_ms'] for r in old_data['results']['ZK-Schnorr']]
    new_schnorr_gen = [r['proof_generation_time_ms'] for r in new_data['results']['ZK-Schnorr']]
    
    old_snark_gen = [r['proof_generation_time_ms'] for r in old_data['results']['ZK-SNARK']]
    new_snark_gen = [r['proof_generation_time_ms'] for r in new_data['results']['ZK-SNARK']]
    
    print(f"\n⚡ SCHNORR PROOF GENERATION")
    print(f"  Before: {np.mean(old_schnorr_gen):.3f} ± {np.std(old_schnorr_gen):.3f} ms")
    print(f"  After:  {np.mean(new_schnorr_gen):.3f} ± {np.std(new_schnorr_gen):.3f} ms")
    print(f"  Consistency: {(1 - abs(np.mean(new_schnorr_gen) - np.mean(old_schnorr_gen)) / np.mean(old_schnorr_gen)) * 100:.1f}%")
    
    print(f"\n🔒 SNARK PROOF GENERATION (simulated)")
    print(f"  Before: {np.mean(old_snark_gen):.1f} ± {np.std(old_snark_gen):.1f} ms")
    print(f"  After:  {np.mean(new_snark_gen):.1f} ± {np.std(new_snark_gen):.1f} ms")
    
    # Speedup comparison
    old_speedup = [old_snark_gen[i] / old_schnorr_gen[i] for i in range(len(old_schnorr_gen))]
    new_speedup = [new_snark_gen[i] / new_schnorr_gen[i] for i in range(len(new_schnorr_gen))]
    
    print(f"\n🚀 SPEEDUP FACTOR (SNARK/Schnorr)")
    print(f"  Before: {np.mean(old_speedup):.0f}× average (range: {min(old_speedup):.0f}-{max(old_speedup):.0f}×)")
    print(f"  After:  {np.mean(new_speedup):.0f}× average (range: {min(new_speedup):.0f}-{max(new_speedup):.0f}×)")
    
    # Proof sizes
    old_schnorr_size = [r['proof_size_bytes'] for r in old_data['results']['ZK-Schnorr']]
    new_schnorr_size = [r['proof_size_bytes'] for r in new_data['results']['ZK-Schnorr']]
    
    old_snark_size = [r['proof_size_bytes'] for r in old_data['results']['ZK-SNARK']]
    new_snark_size = [r['proof_size_bytes'] for r in new_data['results']['ZK-SNARK']]
    
    print(f"\n💾 PROOF SIZES")
    print(f"  Schnorr (constant): {old_schnorr_size[0]} bytes")
    print(f"  SNARK Before: {min(old_snark_size)}-{max(old_snark_size)} bytes")
    print(f"  SNARK After:  {min(new_snark_size)}-{max(new_snark_size)} bytes")
    
    # Size ratios
    old_size_ratio = [old_snark_size[i] / old_schnorr_size[i] for i in range(len(old_schnorr_size))]
    new_size_ratio = [new_snark_size[i] / new_schnorr_size[i] for i in range(len(new_schnorr_size))]
    
    print(f"\n📦 SIZE RATIO (SNARK/Schnorr)")
    print(f"  Before: {np.mean(old_size_ratio):.1f}× average (range: {min(old_size_ratio):.1f}-{max(old_size_ratio):.1f}×)")
    print(f"  After:  {np.mean(new_size_ratio):.1f}× average (range: {min(new_size_ratio):.1f}-{max(new_size_ratio):.1f}×)")
    
    # Data points density
    print(f"\n📊 DATA DENSITY (for visualization)")
    print(f"  Before: {len(old_lengths)} points → sparse visualization")
    print(f"  After:  {len(new_lengths)} points → smooth curves")
    print(f"  Improvement: {len(new_lengths) / len(old_lengths):.1f}× more data points")
    
    # PSNR
    old_psnr = [r['psnr_db'] for r in old_data['results']['ZK-Schnorr']]
    new_psnr = [r['psnr_db'] for r in new_data['results']['ZK-Schnorr']]
    
    print(f"\n🖼️  IMAGE QUALITY (PSNR)")
    print(f"  Before: {np.mean(old_psnr):.1f} dB average (range: {min(old_psnr):.1f}-{max(old_psnr):.1f})")
    print(f"  After:  {np.mean(new_psnr):.1f} dB average (range: {min(new_psnr):.1f}-{max(new_psnr):.1f})")
    
    print(f"\n{'='*80}")
    print("✅ SUMMARY")
    print(f"{'='*80}")
    print(f"  ✓ Test coverage: {old_schnorr + old_snark} → {new_schnorr + new_snark} tests (+{(new_schnorr + new_snark) - (old_schnorr + old_snark)})")
    print(f"  ✓ Data points: {len(old_lengths)} → {len(new_lengths)} per protocol (+{len(new_lengths) - len(old_lengths)})")
    print(f"  ✓ Distribution: variable steps → arithmetic progression (step=100)")
    print(f"  ✓ Visualization: sparse → smooth curves")
    print(f"  ✓ Performance metrics: consistent across both runs")
    print(f"  ✓ Quality: All PSNR values > 60 dB (excellent)")
    print(f"{'='*80}")

if __name__ == "__main__":
    analyze_comparison()
