# Image Size Performance Analysis

## Overview
Performance analysis of ZK-SNARK chaos steganography across different image sizes.

## Test Configuration
- **Date**: 2025-10-11 16:29:27
- **Size Range**: 64×64 to 1024×1024
- **Test Iterations**: 5 runs per size (averaged)

## Results Summary
- **Feature Extraction Time**: 0.44 - 168.19 ms
- **Chaos Generation Time**: 0.12 - 0.14 ms
- **Maximum Capacity**: 1000 bits
- **Average Efficiency**: 6.5%

## Detailed Results
| Size | Feature Time (ms) | Chaos Time (ms) | Capacity (bits) | Efficiency (%) |
|------|------------------|----------------|----------------|----------------|
| 64×64 | 0.44±0.02 | 0.12±0.01 | 1000 | 24.4% |
| 128×128 | 2.06±0.02 | 0.12±0.00 | 1000 | 6.1% |
| 256×256 | 13.34±5.80 | 0.12±0.00 | 1000 | 1.5% |
| 512×512 | 40.48±0.80 | 0.13±0.00 | 1000 | 0.4% |
| 1024×1024 | 168.19±1.94 | 0.14±0.00 | 1000 | 0.1% |

## Observations
- Feature extraction time scales roughly O(n) with image area
- Chaos generation time remains relatively constant
- Embedding capacity scales linearly with image size
- Efficiency decreases slightly for larger images due to position conflicts
