# Proof Size Performance Analysis

## Overview
Performance analysis of ZK-SNARK chaos steganography across different proof sizes.

## Test Configuration
- **Date**: 2025-10-11 16:29:29
- **Image Size**: 256×256 pixels
- **Proof Size Range**: 307 - 72904 bytes
- **Test Iterations**: 3 embedding runs (averaged)

## Results Summary
- **Embedding Time Range**: 22.80 - 95.40 ms
- **Maximum Successful Size**: 4030 bytes

## Detailed Results
| Proof Type | Size (bytes) | Size (bits) | Embed Time (ms) | Embed Success |
|------------|-------------|-------------|----------------|---------------|
| Small | 307 | 2456 | 22.80±0.27 | 100% |
| Medium | 1071 | 8568 | 41.18±0.35 | 100% |
| Large | 4030 | 32240 | 95.40±0.80 | 100% |
| Extra Large | 15638 | 125104 | 0.00±0.00 | 0% |
| Huge | 72904 | 583232 | 0.00±0.00 | 0% |

## Observations
- Embedding time scales with proof size
- Success rate depends on image capacity vs proof size
- Larger proofs may fail due to insufficient embedding positions
