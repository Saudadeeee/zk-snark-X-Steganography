#!/bin/bash
# Run detailed benchmark

cd "$(dirname "$0")"
echo "Running from: $(pwd)"

python3 simplified_detailed_benchmark.py
