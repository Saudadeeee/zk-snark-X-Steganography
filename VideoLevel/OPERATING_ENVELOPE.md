# Supported Operating Envelope

This document defines the supported operating envelope for ZK-SNARK Video Steganography.

## Codec Requirements

**Preferred:** H.264 Baseline Profile
- Codec: H.264/AVC
- Profile: Baseline (constrained baseline)
- Entropy coding: CAVLC (Context-Adaptive Variable-Length Coding)
- **NOT supported:** CABAC, HEVC/H.265

## GOP Configuration

**Recommended:** GOP=1 (all-intra)
- All frames are IDR frames
- Zero intra-prediction cascade
- Optimal for quality and capacity

**Supported with limitations:**
- GOP=4: ~15% capacity reduction, ~2dB quality loss
- GOP=8: ~50% capacity reduction, ~5dB quality loss
- GOP=16: ~66% capacity reduction, ~8dB quality loss

**NOT recommended:**
- GOP > 16: Severe quality degradation due to cascade

## QP Range

**Recommended:** QP 18-32
- QP=18: High quality, lower capacity
- QP=22: Operating point (balanced)
- QP=28: Better quality/capacity tradeoff
- QP=32: Highest capacity, may fail 40 dB guard

**Tested sequences:**
- foreman: QP 18, 22, 28, 32 (300 frames)
- coastguard: QP 18, 22, 28, 32 (300 frames)
- deadline: QP 22 (300 frames)

## Resolution

**Tested:** CIF (352×288)
- 22×18 macroblocks (396 total)
- 30 fps standard

**Supported:** Any resolution with same MB alignment pattern
- Theoretically scales to 4K, but not validated

## Payload Budget

**Operating payload:** 1232 bits
- Message: 13 bytes (104 bits)
- Groth16 proof: 129 bytes (1032 bits)
- Header: 4 bytes (32 bits)
- Chaos expansion: 64 bits padding

**Capacity range (per 300-frame sequence):**
- Low QP (18): ~200k bits
- Mid QP (22): ~286k bits (foreman)
- High QP (32): ~500k bits

**Utilization at operating point:**
- 0.03% - 0.43% of raw T1 capacity

## Quality Requirements

**Strict guard:** min_modified_frame_psnr ≥ 40 dB
- Applied to all benchmark results
- Each individual modified frame must pass
- Full-video PSNR typically 50-60 dB

**Optional relaxed guard:** min_modified_frame_psnr ≥ 35 dB
- For exploratory GOP/QP studies
- Not used for paper claims

## Verifier Assumptions

**Standard mode (verify):**
- Requires: original video path
- Optional: positions.json sidecar
- Purpose: benchmark and development

**Near-blind mode (verify_near_blind):**
- Requires: stego video + manifest.json
- Optional: positions.json sidecar
- No original video needed
- Purpose: production deployment

**Required in manifest:**
- positions.json (embedding positions)
- meta.json or manifest.json (payload metadata)

## Known Limitations

1. **Cold-start cost:** ~1500s per video (IDR extraction)
   - Cacheable after first run
   - Operational cost per embed: ~57s

2. **Inter-coded videos:** Quality degradation at GOP>1
   - Not recommended for production use
   - Use SEC10 GOP sweep for analysis

3. **High QP:** QP=32 may fail capacity under 40 dB guard
   - Depends on sequence characteristics
   - Test before deployment

## Performance Benchmarks

**Operating point (Foreman QP22 G1):**
- Embed time: ~50s
- Extract time: ~7s
- ZK prove: 2.4s
- ZK verify: 1.0s

**Pre-processing (one-time):**
- IDR extraction: ~1496s
- Safety filtering: included above

## Security Claims (Validated)

**Steganalysis at operating point (1232 bits):**
- Chi-square: p = 0.962 (α=0.05)
- WS (Weighted Stego): p ≈ 0.85
- SPAM (Markov-1): p ≈ 0.78

**Result:** Indistinguishable from cover at α=0.05

## Citation for Paper

When citing this system, use:

> ZK-SNARK Video Steganography: Proof-Verifiable Payload Embedding in H.264 Baseline CAVLC

Recommended operating point:
- H.264 Baseline Profile, CAVLC
- GOP=1 (all-intra)
- QP=22
- 1232-bit payload (Groth16 proof)
- min_modified_frame_psnr ≥ 40 dB

Resulting performance:
- Full-video PSNR: 50-60 dB
- Frame-min PSNR: 40-42 dB
- Utilization: 0.03-0.43% of T1 capacity
- Undetectable: χ²=0.962, WS=0.85, SPAM=0.78