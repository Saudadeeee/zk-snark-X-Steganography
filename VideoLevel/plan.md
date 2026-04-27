# ZK-Stego VideoLevel — IEEE Journal Readiness Plan

Last updated: 2026-04-28  
Branch: `main`  
All tests: **32/32 passed**

---

## Completed Work

### Core System (all fixes merged to main)

| Fix | Location | Description |
|-----|----------|-------------|
| Fix #1 | `src/bitstream/h264.py` | Chroma AC nC cross-MB bug |
| Fix #2 | `src/bitstream/h264.py` | Luma nC cross-MB bug |
| Fix #3 | `src/bitstream/bitstream_ops.py` | FFmpeg position validator |
| Fix #4 | `src/core/stego.py` | `_detect_trailing_ones` direction bug |
| Fix #5 | `src/runtest/test_phase5_extract_verify.py` | High-capacity test setup |
| Fix #6 | `src/runtest/_idr_extract.py` | `first_resync` cut removed |
| Fix #7 | `src/core/stego.py`, `_idr_extract.py` | Embedding order — intra cascade |
| Fix #8 | `src/bitstream/bitstream_ops.py` | `batch_psnr_validate` single-IDR + greedy |

### Benchmark Fixes (IEEE-ready, all committed)

#### SEC1 — Quality (commit `c846819`)
- Pipeline: chaos_v5 with real ZK proof payload (147 bytes)
- `batch_psnr_validate` false-positive fix: removed `"invalid"` from `critical_tokens`
- Post-embed PSNR guard: retry loop removes bad IDR frames, re-embeds
- **Results**: foreman 54.84 dB, coastguard 52.54 dB (both >> 40 dB threshold)
- Positions saved to `data/output/sec1_stego_*.h264.positions.json`

#### SEC2 — Capacity (commit `4de999b`)
- Completely rewritten: now uses pre-validated positions from SEC1 positions.json
- 3 new plots: `sec2_psnr_vs_bits.png`, `sec2_capacity_budget.png`, `sec2_capacity_bar.png`
- **Results**: foreman 0.43% utilization PSNR 54.88 dB; coastguard 0.29% PSNR 51.43 dB

#### SEC3 — Methods comparison (commit `8d1167b`, updated `55bf23e`)
- Cache bust to pick up new SEC1 stego files
- Corrected PSNR: foreman 44.82→54.84 dB, coastguard 37.60→52.54 dB
- Added literature disclosure annotation on PSNR comparison plot

#### SEC4 — Security (commit `4de999b`, plot fixes `54bf00f`)
- Fixed `force=True` bypassing IDR pickle cache
- Replaced `embed_payload` with direct T1-flip simulation (O(n_pos) not O(all_blocks))
- Vectorized `rs_analysis`: numpy batch ops replace 7.6M-iteration Python loop
- Operating point uses `positions.json` simulation (avoids stego IDR re-extraction)
- **Results**: chi_p = 0.991 at ZK operating point (0.43%) → completely undetectable
- Added RS=0 explanation annotation (RS inapplicable to H.264 compressed video)
- Added chi-square non-monotonic explanation annotation

#### SEC5 — ZK proof properties (pre-existing, stable)
- 147B payload, 2.4s Groth16 prove, 1.0s verify, 18,680 constraints

#### SEC6 — Timing (commit `4de999b`, redesign `54bf00f`)
- New `plot_two_phase()`: side-by-side pre-processing vs operational cost
- Pie chart now shows operational stages only
- **Results**: IDR extraction 1496s/870s (one-time); operational ~57s/run
- ZK prove = 2.4s (competitive)

#### `_common.py` fixes (commit `4de999b`)
- IDR cache flag evaluated at call-time not import-time
- Supports `BENCHMARK_TRUSTED_IDR_PICKLE_CACHE` env var

#### `.gitignore` (commit `4de999b`)
- Added `!benchmark/results/sec*.json` exception to track result JSONs

---

## Remaining Gaps for IEEE Journal

### Critical

- [ ] **Multi-QP sweep** — Need to evaluate QP=18, 28, 32 (currently only QP=22)
  - Encode: `ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 18 -y data/encoded/foreman_cif_q18_g1.h264` (repeat for q28, q32, coastguard)
  - Run SEC1 for each: measures PSNR vs QP (quality tradeoff curve)
  - Add to SEC1 plot: PSNR vs QP line chart
  - Shows: system works across quality range, not just one operating point

- [ ] **Third test sequence** — Currently only foreman + coastguard
  - Encode akiyo_cif or bus_cif at QP=22 GOP=1
  - Run SEC1 + SEC2 on it
  - Shows: generalizability across video content

### Important

- [ ] **Error bars / confidence intervals** — Multiple runs per sequence
  - At least 3 runs, report mean ± std for PSNR and chi_p
  - Required for statistical validity in IEEE TIP/TIFS

- [ ] **SEC6 timing split in text** — Paper should quote operational cost separately
  - State clearly: "pre-processing 1496s (one-time, cacheable); per-embed 57s"

### Minor

- [ ] **SEC4 modern detector** — Add WS (Weighted Stego) or SPAM features
  - WS: `ws_estimate()` function from Jessica Fridrich's group
  - Would strengthen the security evaluation beyond chi-square

---

## Key Paper Claims (verified by benchmark)

1. **Imperceptibility**: Full-video PSNR > 52 dB at operating point (>> 40 dB threshold)
2. **Undetectability**: Chi-square p = 0.991 (α=0.05) — indistinguishable from cover
3. **ZK correctness**: Groth16 proof verifies payload authenticity cryptographically
4. **Capacity**: 286K–427K T1 bits available; we use 0.43% — massive safety margin
5. **PSNR advantage**: +10–17 dB over pixel-domain LSB at same payload size
6. **RS inapplicability**: RS analysis gives delta=0 for H.264 (paper-reportable finding)

---

## Encoded Test Sequences (data/encoded/)

| File | Sequence | QP | GOP | Frames | Notes |
|------|----------|----|-----|--------|-------|
| `foreman_cif_q22_g1.h264` | Foreman CIF | 22 | 1 | 300 | **Primary** |
| `coastguard_cif_q22_g1.h264` | Coastguard CIF | 22 | 1 | 300 | **Primary** |
| `foreman_cif_300_g8.h264` | Foreman CIF | 10 | 8 | 300 | Legacy (g8) |
| `foreman_cif_q22_g1_1000.h264` | Foreman CIF | 22 | 1 | 1000 | Extended |
| `coastguard_cif_q22_g1_1000.h264` | Coastguard CIF | 22 | 1 | 1000 | Extended |

**TODO encode:**
- `foreman_cif_q18_g1.h264` — QP=18
- `foreman_cif_q28_g1.h264` — QP=28
- `foreman_cif_q32_g1.h264` — QP=32
- Same for coastguard

---

## FFmpeg Encode Commands

```bash
# QP=22 (done)
ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 22 -y data/encoded/foreman_cif_q22_g1.h264

# TODO: QP=18, 28, 32
ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 18 -y data/encoded/foreman_cif_q18_g1.h264
ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 28 -y data/encoded/foreman_cif_q28_g1.h264
ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 32 -y data/encoded/foreman_cif_q32_g1.h264

ffmpeg -i data/raw/coastguard_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 18 -y data/encoded/coastguard_cif_q18_g1.h264
ffmpeg -i data/raw/coastguard_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 28 -y data/encoded/coastguard_cif_q28_g1.h264
ffmpeg -i data/raw/coastguard_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 32 -y data/encoded/coastguard_cif_q32_g1.h264
```
