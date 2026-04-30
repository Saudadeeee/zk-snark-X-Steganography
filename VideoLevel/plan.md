# ZK-Stego VideoLevel — IEEE Journal Readiness Plan

Last updated: 2026-04-30  
Branch: `main`  
All tests: **32/32 passed** (`py -3.12 src/runtest/run_all.py`)

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
- 2026-04-29 fix: `bits_required` now tracks the true chaos-expanded payload (`1232` bits), not the pre-chaos blob (`1176` bits)
- 2026-04-29 fix: all-intra validation now uses headroom + refill after bad-IDR removal, so the benchmark reaches the real operating point instead of under-filling
- 2026-04-30 extension: multi-QP sweep and third-sequence run added to SEC1
- **Results at 1232/1232 bits embedded**:
  - Foreman QP18 = 49.45 dB
  - Foreman QP22 = 54.79 dB
  - Foreman QP28 = 47.61 dB
  - Coastguard QP18 = 52.92 dB
  - Coastguard QP22 = 52.46 dB
  - Coastguard QP28 = 49.00 dB
  - Coastguard QP32 = 48.48 dB
  - Deadline QP22 = 59.03 dB
- `foreman_q32_g1` is currently **not** sustainable at the same operating point on the available 50-frame asset: after bad-IDR removal only 1165 safe positions remain (<1232)
- Positions saved to `data/output/sec1_stego_*.h264.positions.json`

#### SEC2 — Capacity (commit `4de999b`)
- Completely rewritten: now uses pre-validated positions from SEC1 positions.json
- 2026-04-29 fix: sweep payload now reuses the exact SEC1 real-proof + chaos operating payload, not a placeholder chaos key
- 2026-04-30 extension: third-sequence capacity run added (`deadline_q22_g1`)
- 3 new plots: `sec2_psnr_vs_bits.png`, `sec2_capacity_budget.png`, `sec2_capacity_bar.png`
- **Results**:
  - Operating point utilization: foreman 0.43%, coastguard 0.29%
  - Validated pools: foreman 1332 bits, coastguard 1316 bits
  - Deadline validated pool: 1321 bits, utilization 0.071%
  - 100% validated-pool sweep: foreman 50.00 dB at 1328 bits, coastguard 52.28 dB at 1312 bits
  - Deadline 100% validated-pool sweep: 58.76 dB at 1320 bits

#### SEC3 — Methods comparison (commit `8d1167b`, updated `55bf23e`)
- Cache bust to pick up new SEC1 stego files
- Corrected PSNR: foreman 44.82→54.79 dB, coastguard 37.60→52.46 dB
- Added literature disclosure annotation on PSNR comparison plot

#### SEC4 — Security (commit `4de999b`, plot fixes `54bf00f`)
- Fixed `force=True` bypassing IDR pickle cache
- Replaced `embed_payload` with direct T1-flip simulation (O(n_pos) not O(all_blocks))
- Vectorized `rs_analysis`: numpy batch ops replace 7.6M-iteration Python loop
- Operating point uses `positions.json` simulation (avoids stego IDR re-extraction)
- **Results**: chi_p = 0.962 at ZK operating point (0.43%) → still comfortably undetectable at α=0.05
- Added RS=0 explanation annotation (RS inapplicable to H.264 compressed video)
- Added chi-square non-monotonic explanation annotation

#### SEC5 — ZK proof properties (pre-existing, stable)
- 147B payload, 2.4s Groth16 prove, 1.0s verify, 18,680 constraints
- Design assumption locked: Groth16 proof size is treated as fixed for this system configuration, so payload budgeting should assume a stable proof footprint and only the message/packing/chaos expansion changes total embedded bits

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

## Locked Design Assumptions

### Payload sizing

- [x] **Groth16 proof size treated as fixed**
  - For this repository and circuit setup, Groth16 proof size is assumed stable and should not be treated as a sweep variable
  - Capacity planning should therefore budget around a fixed proof footprint, with total payload variation coming from:
    - message length
    - 4-byte packing header
    - chaos padding / bit-expansion
  - Current benchmark operating point remains the chaos-expanded `1232`-bit payload

### Quality floor

- [x] **Primary quality constraint**
  - Preferred paper constraint: `frame-min PSNR > 35–40 dB`
  - Current strict benchmark guard remains the stronger setting: `frame-min PSNR >= 40 dB`
  - Interpretation for future tuning:
    - `>= 40 dB`: target operating point / strongest claim
    - `35–40 dB`: acceptable lower band for exploratory GOP/QP tradeoff studies if bitrate savings are needed

---

### Critical

- [ ] **Symmetric QP sweep dataset** — QP sweep is now implemented, but `foreman_q18/q28/q32` assets are only 50 frames while `coastguard` is 300 frames
  - Preferred next step: prepare longer foreman all-intra QP sweep assets for apples-to-apples comparison
  - `foreman_q32_g1` currently fails the full 1232-bit operating point under the 40 dB frame guard

- [x] **Third test sequence** — `deadline_q22_g1` is now integrated into SEC1 and SEC2
  - Result: 59.03 dB at the 1232-bit operating point
  - Capacity: 1,735,622 raw T1 bits, 1321 validated bits

### Important

- [ ] **Error bars / confidence intervals** — Multiple runs per sequence
  - At least 3 runs, report mean ± std for PSNR and chi_p
  - Required for statistical validity in IEEE TIP/TIFS

- [ ] **SEC6 timing split in text** — Paper should quote operational cost separately
  - State clearly: "pre-processing 1496s (one-time, cacheable); per-embed 57s"

- [x] **Environment reproducibility note** — `requirements.txt` added and validated runtime pinned to `py -3.12`
  - Repo now documents the minimum Python dependencies (`numpy`, `matplotlib`)
  - Paper/runtime claims should still reference the validated environment: `py -3.12`

- [~] **GOP/QP tradeoff study under fixed payload assumption**
  - QP recommendation layer is now implemented in `benchmark/sec7_tradeoff.py`
  - Current fixed-payload recommendations under the strict `frame-min PSNR >= 40 dB` guard:
    - Foreman: best tested QP = 28
    - Coastguard: best tested QP = 32
    - Deadline: best tested QP = 22
  - Remaining work: add an explicit GOP sweep if the paper must claim bitrate-efficient operating points beyond all-intra

### Minor

- [ ] **SEC4 modern detector** — Add WS (Weighted Stego) or SPAM features
  - WS: `ws_estimate()` function from Jessica Fridrich's group
  - Would strengthen the security evaluation beyond chi-square

---

## Key Paper Claims (verified by benchmark)

1. **Imperceptibility**: Full-video PSNR = 54.79 dB (Foreman), 52.46 dB (Coastguard) at the true 1232-bit operating point
2. **Undetectability**: Chi-square p = 0.962 at operating point (α=0.05) — indistinguishable from cover
3. **ZK correctness**: Groth16 proof verifies payload authenticity cryptographically
4. **Capacity**: 286K–427K T1 bits available; we use 0.43% / 0.29% — massive safety margin
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

**Additional encoded assets already present:**
- `foreman_cif_q18_g1.h264`
- `foreman_cif_q28_g1.h264`
- `foreman_cif_q32_g1.h264`
- `coastguard_cif_q18_g1.h264`
- `coastguard_cif_q28_g1.h264`
- `coastguard_cif_q32_g1.h264`
- `deadline_cif_q22_g1.h264`

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
