# ZK-SNARK Steganography Benchmark Tables

All measurements use a 60-character metadata integrity token (480 bits). Test cases cover:
- Lenna 512×512 (reference image)
- Random Noise 1024×1024 (synthetic high-entropy texture)
- Gradient Field 768×768 (structured smooth content)

## Quality & Proof Metrics

| Image/Test Case | System Variant | PSNR (dB) | SSIM | MSE | Capacity (bpp) | Proof Generation Time (s) | Proof Verification Time (s) | Proof Size (KB) | Overhead vs Baseline |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 83.38 | 0.99999998 | 2.99e-04 | 0.00183 | 0.53 | 0.51 | 0.72 | +0.53 s |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 83.38 | 0.99999998 | 2.99e-04 | 0.00183 | 0.53 | 0.51 | 0.72 | +0.53 s |
| Lenna 512×512 | Proposed (Optimized) | 83.38 | 0.99999998 | 2.99e-04 | 0.00183 | 0.55 | 0.52 | 0.72 | +0.55 s |
| Random Noise 1024×1024 | Proposed Method (zk-SNARK) | 89.43 | 0.999999996 | 7.41e-05 | 0.00046 | 0.54 | 0.52 | 0.73 | +0.54 s |
| Random Noise 1024×1024 | Proposed (Optimized) | 89.43 | 0.999999996 | 7.41e-05 | 0.00046 | 0.55 | 0.48 | 0.72 | +0.55 s |
| Gradient Field 768×768 | Proposed Method (zk-SNARK) | 86.75 | 0.999999994 | 1.37e-04 | 0.00081 | 0.54 | 0.51 | 0.72 | +0.54 s |
| Gradient Field 768×768 | Proposed (Optimized) | 86.75 | 0.999999994 | 1.37e-04 | 0.00081 | 0.54 | 0.49 | 0.72 | +0.54 s |

> Baseline rows keep proof-related cells empty because those stages are not executed in the reference variant.

## RAM Consumption

| Image/Test Case | System Variant | RAM (Stego) | RAM (Proving) | RAM (Verifying) |
| --- | --- | --- | --- | --- |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 58.45 MB | 55.43 MB | 55.43 MB |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 58.45 MB | 55.43 MB | 55.43 MB |
| Lenna 512×512 | Proposed (Optimized) | 58.45 MB | 55.43 MB | 55.43 MB |
| Random Noise 1024×1024 | Proposed Method (zk-SNARK) | 92.74 MB | 78.65 MB | 78.65 MB |
| Random Noise 1024×1024 | Proposed (Optimized) | 92.74 MB | 78.65 MB | 78.65 MB |
| Gradient Field 768×768 | Proposed Method (zk-SNARK) | 99.58 MB | 105.12 MB | 105.12 MB |
| Gradient Field 768×768 | Proposed (Optimized) | 99.58 MB | 105.12 MB | 105.12 MB |

RAM values capture process RSS immediately after each stage (embed, prove, verify) using `psutil`.

## Runtime Breakdown

| Image/Test Case | System Variant | Time (Stego) | Time (Proving) | Time (Verifying) | Total Time (s) |
| --- | --- | --- | --- | --- | --- |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 0.0017 s | 0.533 s | 0.510 s | 0.534 s |
| Lenna 512×512 | Proposed Method (zk-SNARK) | 0.0017 s | 0.533 s | 0.510 s | 0.534 s |
| Lenna 512×512 | Proposed (Optimized) | 0.0017 s | 0.547 s | 0.515 s | 0.549 s |
| Random Noise 1024×1024 | Proposed Method (zk-SNARK) | 0.0026 s | 0.539 s | 0.521 s | 0.541 s |
| Random Noise 1024×1024 | Proposed (Optimized) | 0.0026 s | 0.554 s | 0.485 s | 0.556 s |
| Gradient Field 768×768 | Proposed Method (zk-SNARK) | 0.0020 s | 0.541 s | 0.505 s | 0.543 s |
| Gradient Field 768×768 | Proposed (Optimized) | 0.0020 s | 0.535 s | 0.485 s | 0.537 s |

Total time aggregates steganography embedding and proof generation. Optimized measurements reuse witness inputs to reflect a warmed proving pipeline.
