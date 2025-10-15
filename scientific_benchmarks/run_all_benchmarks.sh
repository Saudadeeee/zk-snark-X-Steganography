#!/bin/bash

# Run All Scientific Benchmarks
# ==============================
# Complete benchmark suite for academic publications

echo "================================================================"
echo "  ZK-SNARK Steganography - Scientific Benchmark Suite"
echo "================================================================"
echo ""

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed!"
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"
echo ""

# Check required packages
echo "Checking dependencies..."
python3 -c "import numpy, PIL" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: Required packages not found!"
    echo "Please install: pip install -r requirements.txt"
    exit 1
fi
echo "✓ Core dependencies installed"

python3 -c "import matplotlib, scipy, skimage" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✓ Scientific libraries installed"
    FULL_FEATURES=true
else
    echo "⚠ Scientific libraries not found (plots will be limited)"
    echo "  Install with: pip install matplotlib scipy scikit-image"
    FULL_FEATURES=false
fi

echo ""
echo "================================================================"
echo ""

# Create output directory
OUTPUT_DIR="results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "Output directory: $OUTPUT_DIR"
echo ""

# Step 1: Run main benchmark suite
echo "================================================================"
echo "STEP 1: Running Comprehensive Benchmark Suite"
echo "================================================================"
echo ""

python3 scientific_benchmark_suite.py --output "$OUTPUT_DIR"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Benchmark suite failed!"
    exit 1
fi

echo ""
echo "✓ Benchmark suite completed"
echo ""

# Step 2: Generate comparative analysis
echo "================================================================"
echo "STEP 2: Generating Comparative Analysis"
echo "================================================================"
echo ""

python3 comparative_analysis.py

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠ Comparative analysis failed (non-critical)"
else
    echo ""
    echo "✓ Comparative analysis completed"
fi

echo ""

# Summary
echo "================================================================"
echo "  BENCHMARK SUITE COMPLETED SUCCESSFULLY"
echo "================================================================"
echo ""
echo "Results saved to: $OUTPUT_DIR"
echo ""
echo "Generated artifacts:"
echo "  📊 Figures:"
ls -1 "$OUTPUT_DIR/figures/" 2>/dev/null | sed 's/^/     - /'
echo ""
echo "  📋 Tables:"
ls -1 "$OUTPUT_DIR/tables/" 2>/dev/null | sed 's/^/     - /'
echo ""
echo "  📁 Data:"
ls -1 "$OUTPUT_DIR/data/" 2>/dev/null | sed 's/^/     - /'
echo ""
echo "  📄 Reports:"
ls -1 "$OUTPUT_DIR/"*.md 2>/dev/null | sed 's/^/     - /'
echo ""

# Instructions
echo "================================================================"
echo "  Next Steps for Your Publication"
echo "================================================================"
echo ""
echo "1. Review the summary report:"
echo "   cat $OUTPUT_DIR/SCIENTIFIC_REPORT_*.md"
echo ""
echo "2. Include figures in your paper:"
echo "   \\includegraphics{$OUTPUT_DIR/figures/performance_analysis.pdf}"
echo ""
echo "3. Include LaTeX tables:"
echo "   \\input{$OUTPUT_DIR/tables/performance_metrics.tex}"
echo ""
echo "4. Cite the data for reproducibility:"
echo "   JSON data available in: $OUTPUT_DIR/data/"
echo ""
echo "================================================================"
echo ""

# Optional: Open results directory
if command -v xdg-open &> /dev/null; then
    echo "Opening results directory..."
    xdg-open "$OUTPUT_DIR" 2>/dev/null
elif command -v open &> /dev/null; then
    echo "Opening results directory..."
    open "$OUTPUT_DIR" 2>/dev/null
fi

echo "✅ All benchmarks completed successfully!"
echo ""
