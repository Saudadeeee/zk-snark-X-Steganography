# 📊 ZK-Steganography Scientific Benchmarks

Comprehensive performance benchmarking suite for the ZK-Steganography system.

---

## 📁 Directory Structure

```
scientific_benchmarks/
├── 📊 Main Benchmarks
│   ├── final_detailed_benchmark.py       ⭐ Main 20-point benchmark (RECOMMENDED)
│   ├── comprehensive_benchmark.py        Complete scientific analysis
│   ├── multi_variable_benchmark.py       Multi-variable testing
│   └── comparative_analysis.py           Baseline comparison
│
├── 🔧 Utilities
│   ├── debug_benchmark.py                Anomaly detection tool
│   ├── explain_cache_warming.py          Cache warming visualization
│   ├── export_images.py                  Export charts as images
│   ├── export_tables_as_images.py        Export tables as images
│   └── quick_example.py                  Quick demo for beginners
│
├── 📖 Documentation
│   ├── BENCHMARK_SUMMARY.md              ⭐ Latest results summary
│   ├── CACHE_WARMING_EXPLANATION.md      ⭐ Cache warming guide
│   └── DETAILED_BENCHMARK_DOCUMENTATION.md  Complete technical docs
│
└── 📁 Results
    └── detailed_benchmark_results/       All generated outputs
        ├── benchmark_*.png               High-res charts (300 DPI)
        ├── benchmark_*.pdf               Vector charts
        ├── results_*.json                Raw data
        ├── cache_warming_*.png           Explanation charts
        └── debug_results.json            Debug data
```

---

## 🚀 Quick Start

### Run Main Benchmark (Recommended)
```bash
# Run the complete 20-point benchmark with cache warming
python3 final_detailed_benchmark.py

# Output:
#   • 40 tests (2 benchmarks × 20 points each)
#   • PNG charts (1.2-1.4 MB @ 300 DPI)
#   • PDF charts (65-71 KB, vector)
#   • JSON data files (11-12 KB)
#   • Execution time: ~30-60 seconds
```

### Understand Cache Warming
```bash
# Generate cache warming explanation charts
python3 explain_cache_warming.py

# Output:
#   • 6-panel explanation chart
#   • 2-panel comparison chart
#   • Shows why first test is slower
```

### Debug Anomalies
```bash
# Check for performance anomalies
python3 debug_benchmark.py

# Output:
#   • 8 test sizes (128-1024)
#   • Detailed logging
#   • Anomaly detection
```

---

## 📊 Available Benchmarks

### 1. **Final Detailed Benchmark** ⭐ (Recommended)
**File:** `final_detailed_benchmark.py`

**Features:**
- ✅ 20 data points per benchmark (arithmetic progression)
- ✅ Cache warming (eliminates cold start)
- ✅ 20-panel visualization (4×5 grid)
- ✅ Line charts with clean markers
- ✅ Comprehensive metrics

**Benchmarks:**
1. **Image Size Scaling:** 128×128 → 1024×1024 (fixed message 100 chars)
2. **Message Length Scaling:** 50 → 1000 chars (fixed image 512×512)

**Metrics (20 panels):**
- Row 1: Embedding/Extraction/Total Time, Throughput, Efficiency
- Row 2: RAM Usage, Image Sizes, Overhead, RAM Efficiency
- Row 3: PSNR, SSIM, MSE, Quality Score, Retention
- Row 4: Bits/pixel, Capacity, Time Breakdown, Success Rate, Summary

**Output:**
- PNG: 1.2-1.4 MB @ 300 DPI
- PDF: 65-71 KB (vector)
- JSON: 11-12 KB (raw data)

**Usage:**
```bash
python3 final_detailed_benchmark.py
```

---

### 2. **Debug Benchmark**
**File:** `debug_benchmark.py`

**Features:**
- 8 test sizes (128, 256, 384, 512, 640, 768, 896, 1024)
- Detailed per-test logging
- Anomaly detection (ratio analysis)
- Helps identify performance issues

**Usage:**
```bash
python3 debug_benchmark.py

# Check results:
cat detailed_benchmark_results/debug_results.json
```

---

### 3. **Comprehensive Benchmark**
**File:** `comprehensive_benchmark.py`

**Features:**
- Multiple benchmark types
- Statistical analysis
- Extensive metrics
- Publication-ready

**Usage:**
```bash
python3 comprehensive_benchmark.py
```

---

### 4. **Multi-Variable Benchmark**
**File:** `multi_variable_benchmark.py`

**Features:**
- Tests multiple variables independently:
  - Image sizes (256, 512, 1024, 2048)
  - Message lengths (10, 50, 200, 800, 2000)
  - Message types (text, binary, random)
  - Proof sizes
- Separate analysis per variable
- Comprehensive output

**Usage:**
```bash
python3 multi_variable_benchmark.py
```

---

### 5. **Comparative Analysis**
**File:** `comparative_analysis.py`

**Features:**
- Compare with baseline methods
- Side-by-side comparison
- Statistical significance tests

**Usage:**
```bash
python3 comparative_analysis.py
```

---

## 📖 Documentation

### 1. **Benchmark Summary** ⭐
**File:** `BENCHMARK_SUMMARY.md`

Latest benchmark results with:
- Complete test results
- Performance characteristics
- Visual improvements
- Key findings
- Usage instructions

### 2. **Cache Warming Explanation** ⭐
**File:** `CACHE_WARMING_EXPLANATION.md`

Comprehensive guide covering:
- What is cold start?
- What is cache warming?
- Why it matters for benchmarks
- Implementation examples
- Technical deep dive
- Common pitfalls

### 3. **Detailed Documentation**
**File:** `DETAILED_BENCHMARK_DOCUMENTATION.md`

Complete technical documentation:
- All metrics explained
- Interpretation guide
- Performance characteristics
- Best practices

---

## 📊 Latest Results (Oct 15, 2025)

### Image Size Scaling (20 points)
```
Configuration:
  • Message: 100 chars (fixed)
  • Image: 128×128 → 1024×1024
  • Cache warming: YES

Results:
  • Tests: 20/20 (100%)
  • Time: 3.6 - 9.2 ms
  • RAM: 0.0 - 13.8 MB
  • R²: 0.9876 (excellent fit)
  • Scaling: Linear O(n)
```

### Message Length Scaling (20 points)
```
Configuration:
  • Image: 512×512 (fixed)
  • Message: 50 → 1000 chars
  • Cache warming: YES

Results:
  • Tests: 20/20 (100%)
  • Time: 2.6 - 42.3 ms
  • RAM: ~0 MB overhead
  • R²: 0.9924 (near-perfect)
  • Scaling: Linear O(m)
```

### Key Findings
- ✅ No anomalies at any size
- ✅ Linear scaling confirmed
- ✅ Predictable performance
- ✅ Excellent R² > 0.98

---

## 🎨 Visualization Features

### Chart Improvements (v2.0)
```python
# Optimized markers:
markersize=5      # Smaller, cleaner (was 8)
linewidth=2.5     # Better balance (was 3.0)
markeredgewidth=1 # Subtle outline (was 1.5)
```

**Benefits:**
- ✅ Cleaner professional look
- ✅ Less visual clutter
- ✅ Better readability
- ✅ Easier to see trends

---

## 🔧 Requirements

### Python Dependencies
```bash
# Core requirements:
pip install numpy pillow matplotlib psutil

# Optional (for quality metrics):
pip install scikit-image

# Optional (for statistical analysis):
pip install scipy
```

### System Requirements
- Python 3.8+
- ~100 MB disk space (for outputs)
- ~50 MB RAM (during execution)

---

## 📝 Usage Examples

### Example 1: Quick Benchmark
```bash
# Run main benchmark and view results
python3 final_detailed_benchmark.py
ls -lh detailed_benchmark_results/
```

### Example 2: Custom Analysis
```python
from final_detailed_benchmark import FinalDetailedBenchmark

# Create benchmark instance
bench = FinalDetailedBenchmark()

# Run specific benchmark
bench.run_image_size_benchmark()

# Access results
print(f"Total tests: {len(bench.results)}")
print(f"Avg time: {sum(r['total_time_ms'] for r in bench.results) / len(bench.results):.2f}ms")
```

### Example 3: Debug Performance
```bash
# Check for anomalies
python3 debug_benchmark.py

# View detailed logs
cat detailed_benchmark_results/debug_results.json | jq .
```

---

## 🐛 Troubleshooting

### Issue: scikit-image not found
```
⚠️ scikit-image not available - quality metrics will be zeros

Solution:
pip install scikit-image
```

### Issue: First test is slower
```
This is expected (cold start). Solution:
✅ Use final_detailed_benchmark.py (has cache warming)
✅ Or add warmup run manually
```

### Issue: Out of memory
```
For very large images (>2048×2048):
• Reduce test points (20 → 10)
• Use smaller max size (1024 → 768)
• Close other applications
```

---

## 📊 Output Files

### PNG Charts (High Resolution)
```
Size: 1.2-1.4 MB each
DPI: 300 (publication quality)
Format: RGB
Dimensions: 7200×4800 pixels (24×16 inches)
```

### PDF Charts (Vector)
```
Size: 65-71 KB each
Format: Vector graphics
Scalable: Infinite resolution
Perfect for: Papers, presentations
```

### JSON Data (Raw)
```
Size: 11-12 KB each
Format: Pretty-printed JSON
Contains: All raw measurements
Perfect for: Further analysis
```

---

## 🎯 Best Practices

### 1. Always Use Cache Warming
```python
# ✅ GOOD
warmup()
results = benchmark()

# ❌ BAD
results = benchmark()  # First test will be slower
```

### 2. Use Consistent Test Sizes
```python
# ✅ GOOD: Arithmetic progression
sizes = np.linspace(128, 1024, 20)

# ❌ BAD: Random sizes
sizes = [128, 200, 450, 1024]  # Hard to analyze
```

### 3. Save Raw Data
```python
# Always save JSON for later analysis
with open('results.json', 'w') as f:
    json.dump(results, f, indent=2)
```

### 4. Document Test Conditions
```python
# Include system info in results
results['system'] = {
    'cpu': psutil.cpu_count(),
    'ram': psutil.virtual_memory().total,
    'python': sys.version
}
```

---

## 🔬 Advanced Usage

### Custom Benchmark Configuration
```python
# Modify test parameters
IMAGE_SIZES = np.linspace(256, 2048, 30)  # 30 points instead of 20
MESSAGE_LENGTHS = np.logspace(1, 3, 25)    # Logarithmic scale
WARMUP_RUNS = 3                            # Multiple warmups
```

### Parallel Execution
```python
# NOT RECOMMENDED: Can skew results
# Benchmarks should run sequentially for accuracy
```

### Export to Different Formats
```python
# Export to CSV
import pandas as pd
df = pd.DataFrame(results)
df.to_csv('results.csv', index=False)

# Export to LaTeX
df.to_latex('results.tex')
```

---

## 📚 Additional Resources

### Documentation
- `BENCHMARK_SUMMARY.md` - Latest results
- `CACHE_WARMING_EXPLANATION.md` - Technical guide
- `DETAILED_BENCHMARK_DOCUMENTATION.md` - Complete docs

### Visualization Tools
- `explain_cache_warming.py` - Generate explanation charts
- `export_images.py` - Export in different formats
- `export_tables_as_images.py` - Convert tables to images

### Analysis Tools
- `debug_benchmark.py` - Detect anomalies
- `comparative_analysis.py` - Compare methods
- `multi_variable_benchmark.py` - Multi-factor analysis

---

## 🤝 Contributing

To add new benchmarks:

1. Create new `.py` file in `scientific_benchmarks/`
2. Follow naming convention: `*_benchmark.py`
3. Include docstring with description
4. Save results to `detailed_benchmark_results/`
5. Update this README

---

## 📞 Support

For issues or questions:
- Check `CACHE_WARMING_EXPLANATION.md` for common issues
- Review `BENCHMARK_SUMMARY.md` for latest results
- Run `debug_benchmark.py` to diagnose problems

---

## ✅ Status

**Benchmark Suite:** ✅ Production Ready  
**Last Updated:** October 15, 2025  
**Version:** 2.0 (with improved visualization)  
**Tests Passed:** 40/40 (100%)  
**Documentation:** Complete  

---

**Made with ❤️ for ZK-Steganography**
