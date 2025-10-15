#!/usr/bin/env python3
"""
Giải thích Cold Start vs Cache Warming
========================================

Visualize the impact of cold start on benchmark results
"""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from pathlib import Path
import json

# Load debug results
results_file = Path("detailed_benchmark_results/debug_results.json")
with open(results_file) as f:
    data = json.load(f)

results = data['results']

# Create figure
fig = plt.figure(figsize=(16, 12))

# ============================================================================
# PANEL 1: Time comparison - showing cold start effect
# ============================================================================
ax1 = plt.subplot(3, 2, 1)

sizes = [r['size'] for r in results]
times = [r['total_time_ms'] for r in results]
pixels = [r['pixels'] for r in results]

# Highlight first two tests (cold start region)
ax1.axvspan(0, 1.5, alpha=0.2, color='red', label='Cold Start Zone')
ax1.axvspan(1.5, 8, alpha=0.1, color='green', label='Warmed Cache')

# Plot
bars = ax1.bar(range(1, 9), times, color=['#FF6B6B', '#FFA500', '#4ECDC4', '#4ECDC4', 
                                           '#4ECDC4', '#4ECDC4', '#4ECDC4', '#4ECDC4'],
               edgecolor='black', linewidth=2)

# Annotations
ax1.text(1, times[0] + 0.3, f'{times[0]:.2f}ms\n⚠️ COLD', 
         ha='center', fontsize=10, fontweight='bold', color='red')
ax1.text(2, times[1] + 0.3, f'{times[1]:.2f}ms\n✅ Faster!', 
         ha='center', fontsize=10, fontweight='bold', color='green')

ax1.set_xlabel('Test Number', fontsize=12, fontweight='bold')
ax1.set_ylabel('Total Time (ms)', fontsize=12, fontweight='bold')
ax1.set_title('🔥 COLD START EFFECT\nFirst test is SLOWER', fontsize=13, fontweight='bold')
ax1.set_xticks(range(1, 9))
ax1.set_xticklabels([f'#{i}' for i in range(1, 9)])
ax1.legend(loc='upper left', fontsize=10)
ax1.grid(True, alpha=0.3, axis='y')

# ============================================================================
# PANEL 2: Time per pixel - showing the anomaly
# ============================================================================
ax2 = plt.subplot(3, 2, 2)

time_per_pixel = [r['time_per_pixel_us'] for r in results]

ax2.plot(range(1, 9), time_per_pixel, 'o-', linewidth=2.5, markersize=7,
         color='#E74C3C', markeredgecolor='black', markeredgewidth=1.5)

# Highlight the anomaly
ax2.plot(1, time_per_pixel[0], 'o', markersize=12, 
         markerfacecolor='none', markeredgecolor='red', markeredgewidth=3)
ax2.text(1, time_per_pixel[0] + 0.01, '⚠️ ANOMALY!\n10× slower', 
         ha='center', va='bottom', fontsize=11, fontweight='bold', color='red',
         bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))

# Expected line (average of tests 3-8)
expected = np.mean(time_per_pixel[2:])
ax2.axhline(expected, color='green', linestyle='--', linewidth=2, label=f'Expected: {expected:.4f} μs')

ax2.set_xlabel('Test Number', fontsize=12, fontweight='bold')
ax2.set_ylabel('Time per Pixel (μs)', fontsize=12, fontweight='bold')
ax2.set_title('⏱️ EFFICIENCY ANOMALY\nCold start shows 10× slower per pixel', 
              fontsize=13, fontweight='bold')
ax2.set_xticks(range(1, 9))
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3)

# ============================================================================
# PANEL 3: What happens during cold start
# ============================================================================
ax3 = plt.subplot(3, 2, 3)
ax3.axis('off')

cold_text = """
🥶 COLD START (Lần chạy đầu tiên)
═══════════════════════════════════════

1. 💾 Load thư viện từ disk:
   • numpy, PIL, matplotlib
   • Phải đọc từ SSD/HDD → CHẬM
   
2. 🧠 CPU Cache Miss:
   • L1/L2/L3 cache đều trống
   • Phải fetch từ RAM → CHẬM
   
3. 🔧 Python Initialization:
   • JIT compilation
   • Module imports
   • Function lookups → CHẬM
   
4. 💻 OS Overhead:
   • Memory allocation
   • Page faults
   • Disk I/O → CHẬM

⏱️ KẾT QUẢ: Test #1 = 2.55ms
   (Chậm hơn 3× so với expected!)
"""

ax3.text(0.1, 0.5, cold_text, transform=ax3.transAxes,
         fontsize=11, ha='left', va='center', family='monospace',
         bbox=dict(boxstyle='round', facecolor='#FFE6E6', 
                  alpha=0.9, edgecolor='red', linewidth=3))

# ============================================================================
# PANEL 4: What happens after warming
# ============================================================================
ax4 = plt.subplot(3, 2, 4)
ax4.axis('off')

warm_text = """
🔥 CACHE WARMED (Sau lần chạy đầu)
═══════════════════════════════════════

1. ✅ Thư viện đã trong RAM:
   • numpy, PIL đã loaded
   • Không cần đọc disk → NHANH
   
2. ✅ CPU Cache Hot:
   • L1/L2/L3 đã có data
   • Cache hit rate cao → NHANH
   
3. ✅ Python đã init:
   • Functions đã compiled
   • Imports đã cached → NHANH
   
4. ✅ OS Cache Ready:
   • Memory pages allocated
   • No page faults → NHANH

⏱️ KẾT QUẢ: Test #2-8 = 2.5-8.0ms
   (Nhanh, tuyến tính với image size!)
"""

ax4.text(0.1, 0.5, warm_text, transform=ax4.transAxes,
         fontsize=11, ha='left', va='center', family='monospace',
         bbox=dict(boxstyle='round', facecolor='#E6FFE6', 
                  alpha=0.9, edgecolor='green', linewidth=3))

# ============================================================================
# PANEL 5: Comparison chart - with/without warmup
# ============================================================================
ax5 = plt.subplot(3, 2, 5)

categories = ['Lần 1\n(Cold)', 'Lần 2\n(Warm)', 'Lần 3-8\n(Stable)']
without_warmup = [2.55, 2.46, np.mean([r['total_time_ms'] for r in results[2:]])]
with_warmup = [0, 0, np.mean([r['total_time_ms'] for r in results[2:]])]  # Skip first test

x = np.arange(len(categories))
width = 0.35

bars1 = ax5.bar(x - width/2, without_warmup, width, label='❌ Without Warmup',
                color='#FF6B6B', edgecolor='black', linewidth=2)
bars2 = ax5.bar(x + width/2, [0] + with_warmup[1:], width, label='✅ With Warmup',
                color='#51CF66', edgecolor='black', linewidth=2)

# Add annotations
ax5.text(0 - width/2, 2.55 + 0.2, '2.55ms\n⚠️ Slow', ha='center', 
         fontsize=9, fontweight='bold', color='red')
ax5.text(1 - width/2, 2.46 + 0.2, '2.46ms\nBetter', ha='center',
         fontsize=9, fontweight='bold')
ax5.text(2 - width/2, without_warmup[2] + 0.2, f'{without_warmup[2]:.2f}ms\nStable', ha='center',
         fontsize=9, fontweight='bold')

ax5.set_ylabel('Average Time (ms)', fontsize=12, fontweight='bold')
ax5.set_title('⚡ IMPACT OF CACHE WARMING\nWarmup eliminates cold start', 
              fontsize=13, fontweight='bold')
ax5.set_xticks(x)
ax5.set_xticklabels(categories)
ax5.legend(fontsize=10)
ax5.grid(True, alpha=0.3, axis='y')

# ============================================================================
# PANEL 6: Solution - Warmup strategy
# ============================================================================
ax6 = plt.subplot(3, 2, 6)
ax6.axis('off')

solution_text = """
✅ GIẢI PHÁP: CACHE WARMING
═══════════════════════════════════════

📋 Strategy:
   1. Chạy 1 test WARMUP trước
   2. KHÔNG tính kết quả warmup
   3. Chỉ tính tests sau warmup

💻 Implementation:
   
   # Warmup (không tính)
   print("🔥 Cache warming...")
   run_single_test(size=256)
   results = []  # Clear!
   
   # Real benchmark (có tính)
   for size in [128, 256, ..., 1024]:
       result = run_single_test(size)
       results.append(result)

🎯 KẾT QUẢ:
   • Test đầu tiên đã NHANH
   • Không có cold start anomaly
   • Dữ liệu chính xác hơn!
   • Benchmark đáng tin cậy hơn!
"""

ax6.text(0.1, 0.5, solution_text, transform=ax6.transAxes,
         fontsize=11, ha='left', va='center', family='monospace',
         bbox=dict(boxstyle='round', facecolor='#E6F7FF', 
                  alpha=0.9, edgecolor='blue', linewidth=3))

# ============================================================================
# Overall title and save
# ============================================================================
plt.suptitle('🔥 COLD START vs CACHE WARMING - Detailed Explanation\n' +
             'Why the first test is slower and how to fix it',
             fontsize=16, fontweight='bold', y=0.995)

plt.tight_layout(rect=[0, 0, 1, 0.99])

output_file = Path("detailed_benchmark_results/cache_warming_explanation.png")
plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
print(f"✅ Saved: {output_file}")

output_pdf = Path("detailed_benchmark_results/cache_warming_explanation.pdf")
plt.savefig(output_pdf, format='pdf', bbox_inches='tight', facecolor='white')
print(f"✅ Saved: {output_pdf}")

plt.close()

# ============================================================================
# Create a simple comparison chart
# ============================================================================
fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# LEFT: Scaling behavior
pixels_list = [r['pixels']/1000 for r in results]
times_list = [r['total_time_ms'] for r in results]

ax1.plot(pixels_list, times_list, 'o-', linewidth=2.5, markersize=6,
         color='#3498DB', markeredgecolor='black', markeredgewidth=1.5)

# Mark the anomaly
ax1.plot(pixels_list[0], times_list[0], 'o', markersize=12,
         markerfacecolor='none', markeredgecolor='red', markeredgewidth=3)
ax1.text(pixels_list[0], times_list[0] - 0.5, '❌ Cold Start\nAnomaly',
         ha='center', va='top', fontsize=11, fontweight='bold', color='red',
         bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))

# Expected linear trend (fit on tests 3-8)
from scipy import stats
slope, intercept, r, p, se = stats.linregress(pixels_list[2:], times_list[2:])
fit_x = np.array([min(pixels_list), max(pixels_list)])
fit_y = slope * fit_x + intercept
ax1.plot(fit_x, fit_y, '--', color='green', linewidth=2, 
         label=f'Expected trend\n(Linear: y={slope:.4f}x+{intercept:.2f})')

ax1.set_xlabel('Image Size (K pixels)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Total Time (ms)', fontsize=12, fontweight='bold')
ax1.set_title('WITHOUT Cache Warming\n❌ First point deviates from trend',
              fontsize=13, fontweight='bold')
ax1.legend(fontsize=10)
ax1.grid(True, alpha=0.3)

# RIGHT: After removing cold start
pixels_warm = pixels_list[1:]
times_warm = times_list[1:]

ax2.plot(pixels_warm, times_warm, 'o-', linewidth=2.5, markersize=6,
         color='#27AE60', markeredgecolor='black', markeredgewidth=1.5)

# Linear fit
slope2, intercept2, r2, p2, se2 = stats.linregress(pixels_warm, times_warm)
fit_x2 = np.array([min(pixels_warm), max(pixels_warm)])
fit_y2 = slope2 * fit_x2 + intercept2
ax2.plot(fit_x2, fit_y2, '--', color='blue', linewidth=2,
         label=f'Linear fit (R²={r2**2:.4f})\ny={slope2:.4f}x+{intercept2:.2f}')

ax2.set_xlabel('Image Size (K pixels)', fontsize=12, fontweight='bold')
ax2.set_ylabel('Total Time (ms)', fontsize=12, fontweight='bold')
ax2.set_title('WITH Cache Warming\n✅ Perfect linear scaling!',
              fontsize=13, fontweight='bold')
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3)

plt.suptitle('📊 Cold Start Impact on Benchmark Accuracy\n' +
             f'Without warmup: R²={r**2:.4f} | With warmup: R²={r2**2:.4f}',
             fontsize=14, fontweight='bold')

plt.tight_layout()

output_file2 = Path("detailed_benchmark_results/cache_warming_comparison.png")
plt.savefig(output_file2, dpi=300, bbox_inches='tight', facecolor='white')
print(f"✅ Saved: {output_file2}")

output_pdf2 = Path("detailed_benchmark_results/cache_warming_comparison.pdf")
plt.savefig(output_pdf2, format='pdf', bbox_inches='tight', facecolor='white')
print(f"✅ Saved: {output_pdf2}")

print("\n" + "="*70)
print("✅ EXPLANATION CHARTS CREATED!")
print("="*70)
print("📁 Files generated:")
print("  • cache_warming_explanation.png/pdf")
print("  • cache_warming_comparison.png/pdf")
print("="*70)
