# ZK-SNARK Overhead Analysis

## Overview
Detailed analysis of computational overhead in ZK-SNARK chaos steganography.

## Summary Statistics
- **Average Total Processing Time**: 119.05 ms
- **Average Memory Overhead**: 0.61 MB

## Component Analysis
| Component | Avg Time (ms) | % of Total |
|-----------|---------------|------------|
| Bit Embedding | 66.20 | 55.6% |
| Position Selection | 1.12 | 0.9% |
| Image Saving | 31.02 | 26.1% |
| Image Loading | 7.42 | 6.2% |
| Proof Processing | 2.24 | 1.9% |
| Chaos Generation | 11.04 | 9.3% |

## Key Findings
- Chaos generation is typically the most computationally expensive component
- Memory overhead scales with proof complexity
- Image size significantly impacts total processing time
- Position selection has minimal overhead
