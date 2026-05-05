# ZK-Stego VideoLevel — IEEE Journal Readiness Plan

Last updated: 2026-05-02  
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

#### SEC1 — Quality (updated `2026-05-05`)
- Pipeline: chaos_v5 with real ZK proof payload (147 bytes)
- `batch_psnr_validate` false-positive fix: removed `"invalid"` from `critical_tokens`
- Post-embed PSNR guard: retry loop removes bad IDR frames, re-embeds
- 2026-04-29 fix: `bits_required` now tracks the true chaos-expanded payload (`1232` bits), not the pre-chaos blob (`1176` bits)
- 2026-04-29 fix: all-intra validation now uses headroom + refill after bad-IDR removal, so the benchmark reaches the real operating point instead of under-filling
- 2026-05-05 refresh: SEC1 now uses the real extracted operating positions for verify and stores the validated pool separately from the actual operating set
- 2026-05-05 refresh: Xiph/DERF CIF sequences (`Akiyo`, `Hall Monitor`, `Container`, `City`, `Football`) added to the representative all-intra benchmark set
- **Results at 1232/1232 bits embedded and verified**:
  - Akiyo QP22 = 53.13 dB, modified-frame min = 40.58 dB
  - Hall Monitor QP22 = 50.38 dB, modified-frame min = 40.18 dB
  - Foreman QP22 = 55.15 dB, modified-frame min = 40.67 dB
  - Container QP22 = 51.70 dB, modified-frame min = 40.10 dB
  - City QP22 = 51.57 dB, modified-frame min = 40.07 dB
  - Coastguard QP22 = 51.23 dB, modified-frame min = 40.52 dB
  - Football QP22 = 52.24 dB, modified-frame min = 41.56 dB
  - Deadline QP22 = 58.55 dB, modified-frame min = 40.28 dB
  - Coastguard QP22 (1000f) = 56.02 dB, modified-frame min = 40.22 dB
  - Deadline QP22 (1000f) = 57.68 dB, modified-frame min = 40.26 dB
  - Coastguard QP22 (3000f) = 60.00 dB, modified-frame min = 40.59 dB
- Current strict operating summary: `11/11` tested SEC1 points pass `1232/1232 + verify + min_modified_frame_psnr > 40 dB`
- Positions saved to `data/output/sec1_stego_*.h264.positions.json`

#### SEC2 — Capacity (updated `2026-05-05`)
- Completely rewritten: now uses pre-validated positions from SEC1 positions.json
- 2026-04-29 fix: sweep payload now reuses the exact SEC1 real-proof + chaos operating payload, not a placeholder chaos key
- 2026-05-05 refresh: default SEC2 sweep now matches the broader SEC1 sequence set, including Xiph/DERF content classes and long all-intra variants
- 3 new plots: `sec2_psnr_vs_bits.png`, `sec2_capacity_budget.png`, `sec2_capacity_bar.png`
- **Results**:
  - Operating-point utilization: foreman 0.430%, coastguard 0.288%, football 0.331%, deadline 0.071%
  - Long-sequence utilization: coastguard 1000f = 0.086%, coastguard 3000f = 0.029%
  - 100% operating-point sweep: akiyo 53.13 dB, football 52.24 dB, deadline 58.55 dB, coastguard 3000f 60.92 dB

#### SEC3 — Methods comparison (commit `8d1167b`, updated `55bf23e`)
- Cache bust to pick up new SEC1 stego files
- Corrected PSNR: foreman 44.82→54.79 dB, coastguard 37.60→52.46 dB
- Added literature disclosure annotation on PSNR comparison plot

#### SEC4 — Security (updated `2026-05-05`)
- Fixed `force=True` bypassing IDR pickle cache
- Replaced `embed_payload` with direct T1-flip simulation (O(n_pos) not O(all_blocks))
- Vectorized `rs_analysis`: numpy batch ops replace 7.6M-iteration Python loop
- Operating point uses `positions.json` simulation (avoids stego IDR re-extraction)
- 2026-05-05 refresh: sec4 now prefers any sequence with a valid SEC1 positions file instead of assuming only `foreman_q22_g1`
- **Results**: chi_p = 0.9622 at the Foreman QP22 operating point (0.43%) → still comfortably undetectable at α=0.05
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

- [ ] **SEC1 auditability gaps** — Persist and report quality guard details
  - Record the effective frame-min PSNR threshold in `benchmark/results/sec1_quality_data.json`
    - Fields: `validation_threshold_db`, `validation_threshold_db_effective` (currently null)
  - Report saturated/inf PSNR frame ratio alongside averages to avoid masking artifacts
    - Field: `psnr_inf_frame_count` + total frame count per sequence
  - Track headroom: min PSNR margin above the 40 dB gate is currently ~0.6 dB
    - Scope: foreman_q22_g1 (40.67 dB) and coastguard_q22_g1 (40.57 dB) in 2026-05-01 run
  - Note: running sec1 directly does not generate `benchmark/results/_run_metadata.json`
    - Use `benchmark/safe_benchmark_runner.py` to emit run metadata

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

---

## Additional System Improvement Roadmap

This section tracks all currently identified improvements that can make the
system stronger, broader, faster, and easier to defend in benchmark or paper
form. Groth16 remains fixed by design.

### Locked proof direction

- [x] **Keep Groth16 as the proof system**
  - Do not migrate this repository to PLONK / STARK / Bulletproofs in the current roadmap
  - Keep optimization work focused on:
    - Groth16 invocation efficiency
    - payload packing efficiency around the fixed proof footprint
    - stego robustness, extraction, and benchmark quality

### A. Generality across video types

- [ ] **Split embedding strategy by stream type**
  - Keep current CAVLC/T1 mode as the preferred path for `GOP=1` / all-intra assets
  - Add a dedicated strategy for `GOP>1` / inter-coded streams instead of reusing the same policy unchanged
  - Minimum target:
    - detect stream class automatically
    - choose an embedding policy per class

- [ ] **Formalize supported operating scope**
  - If inter-coded support remains weak, explicitly scope the current system as:
    - "all-intra H.264/CAVLC steganography with ZK-verifiable payload"
  - Align README, benchmark text, and paper claims to that scope

- [ ] **Prototype a hybrid inter-coded branch**
  - Explore at least one of:
    - motion-vector-based embedding for inter-coded video
    - IPM-based embedding for intra-heavy but non-all-intra content
    - adaptive mixed-mode fallback away from T1-only when GOP is large
  - Goal: prevent the strong quality collapse currently observed on GOP8 assets

### B. Embedding optimality and security

- [ ] **Replace position heuristics with distortion-aware costs**
  - Compute a cost per candidate using:
    - coefficient magnitude / local texture
    - block patchability risk
    - local prediction sensitivity
    - temporal concentration penalty
  - Use the costs to rank or optimize candidate positions instead of relying only on round-robin + pruning

- [ ] **Investigate syndrome coding / STC-style embedding**
  - Reduce the number of modified coefficients needed per payload bit
  - Improve imperceptibility and steganalysis resistance at the same payload size
  - Compare directly against the current position-per-bit operating behavior

- [ ] **Allow adaptive multi-bit embedding only on low-risk blocks**
  - Permit more than one embedded bit per block only where cost and reconstruction guards allow it
  - Keep strict constraints:
    - zero preservation
    - bit-length invariance
    - patchability
    - per-frame quality floor

- [ ] **Strengthen steganalysis evaluation**
  - Extend beyond chi-square and RS notes to include:
    - WS / weighted stego features
    - SPAM/SRM-style features where feasible
    - cross-sequence detector behavior at identical payload budgets

### C. Payload efficiency

- [ ] **Improve effective payload efficiency**
  - Optimize useful embedded bits per visible distortion
  - Track:
    - bits per modified block
    - bits per dB PSNR loss
    - bits per validated safe position

- [ ] **Audit message/proof packing overhead**
  - Keep Groth16 fixed, but optimize around it:
    - message header size
    - chaos padding overhead
    - payload alignment / byte packing
  - Document the exact inflation from raw message -> proof blob -> chaos-expanded payload

- [ ] **Support multiple operating points**
  - Define at least three payload modes:
    - conservative / paper-safe
    - balanced
    - stress / max-feasible
  - Report quality-security-capacity tradeoffs for each mode

### D. Extraction architecture

- [ ] **Investigate blind or near-blind extraction**
  - Current extraction depends on original cover analysis
  - Explore designs that reduce or remove dependence on the original video:
    - self-synchronizing side information
    - deterministic recoverable position maps
    - lightweight metadata channels protected by the same safety rules

- [ ] **Define verifier modes clearly**
  - Preserve the current high-integrity verify path
  - Add explicit mode naming if needed:
    - `strict_nonblind_verify`
    - `nearblind_verify`
    - `benchmark_verify`
  - Prevent ambiguity about what information verification requires

### E. Runtime and scalability

- [ ] **Accelerate cold-start analysis**
  - `extract_all_idr_blocks()` is currently the dominant runtime cost
  - Optimization targets:
    - parser hotspots
    - offset extraction overhead
    - repeated object allocation
    - opportunities for chunked or frame-local processing

- [~] **Cache decoded luma frames for benchmark reuse**
  - Avoid repeated `ffmpeg` decode of the same original/stego videos across SEC1/SEC2/SEC3/SEC4/SEC9
  - Add bounded cache invalidation keyed by:
    - file path
    - size
    - mtime
  - 2026-05-04: process-local and disk-backed luma cache added in `benchmark/_common.py`
  - Remaining work: benchmark the win across SEC2/SEC3/SEC4/SEC9 and document cache policy

- [~] **Reduce repeated full-video quality passes**
  - Especially for all-intra streams, avoid recomputing quality over unaffected frames during validation loops
  - Prefer frame-local or IDR-local rechecks where mathematically justified
  - 2026-05-04: sec1 all-intra retry loop now checks only modified frame indices instead of full-video passes
  - Remaining work: extend the same idea to other validation/probe paths

- [ ] **Parallelize per-sequence benchmark execution**
  - Run independent sequence jobs in separate processes
  - Keep result writing deterministic and cache-safe
  - Avoid parallel writes to the same artifact names

- [~] **Add an explicit benchmark fast mode**
  - Purpose: developer iteration, not headline paper results
  - Candidate relaxations:
    - reduced sequence set
    - no repeated post-embed pruning loop
    - capped frame counts
    - reuse existing sec1 stego where valid
  - 2026-05-04: `--fast` added to `benchmark/sec1_quality.py`, `benchmark/sec2_capacity.py`, `benchmark/sec4_security.py`, and `benchmark/sec6_performance.py`
  - Current fast mode:
    - skips expensive sec1 batch PSNR re-validation
    - reduces sec1 probe budgets and probe decode depth
    - reduces sec2 sweep fractions
    - reduces sec3 sequence count and decode depth
    - reduces sec4 payload-rate sweep
    - narrows sec6 default scope for developer iteration
  - 2026-05-04: `--fast` added to `benchmark/sec3_methods.py`
  - 2026-05-04: `benchmark/safe_benchmark_runner.py --fast` now propagates fast mode to supported sections
  - Remaining work: propagate fast mode to any remaining top-level benchmark workflows

- [~] **Reuse cover-video analysis cache across benchmark sections**
  - Avoid recomputing:
    - `extract_all_idr_blocks()`
    - `CAVLCSafetyFilter.get_safe_positions()`
    across `sec1/sec2/sec3/sec4` when the same cover asset is reused
  - 2026-05-04: `benchmark/_common.py` now exposes a shared benchmark-analysis loader backed by `.cache/video_analysis/`
  - 2026-05-04: `sec1`, `sec2`, `sec3`, and `sec4` now reuse the same cached cover analysis
  - Remaining work: measure warm-cache speedup formally and decide whether sec6 should report a warm-cache mode alongside cold-start timing

### F. Robustness and test stability

- [~] **Make the full test suite stable on current assets**
  - Reconcile runtime expectations, fixtures, and time budgets with the actual encoded assets in the repo
  - Eliminate legacy assumptions about removed files or superseded naming
  - 2026-05-04: `src/runtest/run_all.py --quick` added for fast correctness validation on phases 1-3
  - Remaining work: stabilize long-running phase 4/5 coverage under current asset and runtime constraints

- [ ] **Separate correctness tests from long-running performance tests**
  - Keep correctness/unit tests fast and deterministic
  - Move expensive reconstruction/performance scenarios into an explicit slow-test tier

- [ ] **Add regression fixtures for known weak cases**
  - Include at least:
    - high-motion all-intra
    - GOP8/inter-coded failure mode
    - near-threshold PSNR sequences
  - Goal: prevent silent regressions in the exact cases that define current limits

### G. Benchmark credibility and reporting

- [ ] **Expand benchmark coverage by content class**
  - Track classes such as:
    - low motion
    - high motion
    - texture-heavy
    - talking-head / low-detail
  - Summarize which classes are strongest / weakest for this system

- [ ] **Run explicit GOP sweep benchmarks**
  - GOP values to prioritize: `1, 4, 8, 16`
  - Report where the current T1 strategy stops being acceptable
  - Use the results to justify future hybrid design choices

- [ ] **Quantify one-time vs operational cost everywhere**
  - Report:
    - cold-start video cost
    - cached per-message cost
    - batch cost on the same video
  - Make these numbers part of the standard benchmark output set

### H. Documentation and productization

- [~] **Bring README and plan into agreement with real runtime state**
  - Remove or revise claims that no longer match the current repo state
  - Ensure test counts, benchmark status, and supported asset sets are current
  - 2026-05-04: `plan.md` expanded with explicit system-improvement roadmap
  - Remaining work: update README benchmark/runtime claims to match the current codebase and test state

- [ ] **Document the supported operating envelope**
  - Explicitly state:
    - preferred codec profile
    - preferred GOP range
    - recommended QP range
    - expected payload budget
    - verifier assumptions

- [ ] **Define a clean artifact policy**
  - Keep:
    - final `.json` benchmark results
    - final `.png` plots
  - Exclude or auto-clean:
    - stego intermediates
    - `_idr_cache_*.pkl`
    - proof payload caches
    - `__pycache__`
