# ZK-SNARK Video Steganography

Hide a Groth16 zero-knowledge proof inside H.264 baseline video by modifying CAVLC coefficients in IDR frames.

**Status:** IEEE-ready with validated all-intra benchmark path  
**Validated Runtime:** `py -3.12`  
**Tests:** 32/32 passed (Phase 1-5)  
**Benchmark Sections:** SEC1-SEC10 (Quality, Capacity, Methods, Security, Performance, Tradeoff, Real-time, Motion/GOP, Statistical, Audit)

---

## Overview

The system embeds a message-authentication proof into H.264 bitstreams without leaving the compressed-domain workflow. It:

1. Generates a Groth16 proof for the payload.
2. Packs `[4B message_length][message][129B compressed proof]`.
3. Optionally applies chaos transforms:
   - Arnold Cat Map on payload bits
   - Logistic Map on embedding-position order
4. Locates CAVLC-safe positions in IDR frames.
5. Applies length-preserving coefficient/sign modifications.
6. Reconstructs a valid H.264 bitstream.
7. Extracts and verifies the proof from the stego video.

### New Features (IEEE-ready)

- **Versioned Manifest Schema** (v1.0.0): Structured sidecar files with signing hooks
- **Near-Blind Verification**: Reduced cover dependency via manifest-driven extraction
- **Statistical Benchmarking**: Multi-run error bars for IEEE TIP/TIFS validity (≥3 runs)
- **Audit Logging**: SEC1 quality guard tracking with reason logs
- **Modern Detectors**: WS and SPAM steganalysis features
- **Optimized Extraction**: Parallel IDR parsing with vectorization
- **GOP Sweep Analysis**: Quality/capacity tradeoff across GOP=1,4,8,16

### Payload format

- Compressed Groth16 proof size: `129` bytes
- Example benchmark message: `13` bytes (`b"ZK-bench-v1.0!"`)
- Packed blob: `4 + 13 + 129 = 146` bytes = `1168` bits
- Chaos-expanded operating payload used by benchmarks: `1232` bits

### Circuit

`PayloadVerify` proves:

```text
commitment = SHA256(SHA256(message) || secret_key)
```

**Constraint Count:** 18,680 (Groth16)

Public inputs:
- `payload_hash[256]`
- `commitment[256]`
- `payload_length`

Private input:
- `secret[256]`

---

## Current Benchmark Snapshot

All results below were regenerated on `2026-05-22` using the real proof pipeline and `py -3.12`.

### SEC1: Quality at the 1232-bit operating point

All listed operating points satisfy:
- Full real-proof embedding: `1232/1232` bits
- End-to-end proof verification
- `min_modified_frame_psnr > 40 dB`

| Sequence | Full-video PSNR | Min Modified-Frame PSNR | Avg SSIM | Embedded bits |
|---|---:|---:|---:|---:|
| Akiyo QP22 G1 | 53.13 dB | 40.58 dB | 0.9997 | 1232/1232 |
| Hall Monitor QP22 G1 | 50.38 dB | 40.18 dB | 0.9997 | 1232/1232 |
| Foreman QP22 G1 | 55.15 dB | 40.67 dB | 0.9998 | 1232/1232 |
| Container QP22 G1 | 51.70 dB | 40.10 dB | 0.9998 | 1232/1232 |
| City QP22 G1 | 51.57 dB | 40.07 dB | 0.9998 | 1232/1232 |
| Coastguard QP22 G1 | 51.23 dB | 40.52 dB | 0.9997 | 1232/1232 |
| Football QP22 G1 | 52.24 dB | 41.56 dB | 0.9997 | 1232/1232 |
| Deadline QP22 G1 | 58.55 dB | 40.28 dB | 1.0000 | 1232/1232 |
| Coastguard QP22 G1 (1000f) | 56.02 dB | 40.22 dB | 0.9999 | 1232/1232 |
| Deadline QP22 G1 (1000f) | 57.68 dB | 40.26 dB | 0.9999 | 1232/1232 |
| Coastguard QP22 G1 (3000f) | 60.00 dB | 40.59 dB | 1.0000 | 1232/1232 |

**Operating-point success rate:** 11/11 sequences pass strict criterion with proof verification.

### SEC2: Capacity

| Sequence | Raw T1 capacity | Operating positions | Utilization | PSNR @ 1232 bits |
|---|---:|---:|---:|---:|
| Foreman QP22 G1 | 286,745 bits | 1,232 bits | 0.430% | 55.15 dB |
| Coastguard QP22 G1 | 427,883 bits | 1,232 bits | 0.288% | 51.23 dB |
| Football QP22 G1 | 372,266 bits | 1,232 bits | 0.331% | 52.24 dB |
| Deadline QP22 G1 | 1,735,622 bits | 1,232 bits | 0.071% | 58.55 dB |

### SEC4: Steganalysis

- Foreman QP22 G1: `chi-square p = 0.9622` (α=0.05 threshold)
- SPA at operating point: `0.03762`
- RS delta: `0.0` (inapplicable to H.264 CAVLC)
- WS detector: `p ≈ 0.85` (undetectable at α=0.05)
- SPAM detector: `p ≈ 0.78` (undetectable at α=0.05)

### SEC6: Performance

- **Pre-processing** (one-time, cacheable): `~1496s` per video
- **Operational cost** (per-embed): `~57s`
- ZK proof generation: `2.4s` (competitive)
- Luma frame decode cached across benchmarks

### SEC10: GOP Sweep

| GOP Size | Min Frame PSNR | Effective Capacity | Cascade Score |
|---|---:|---:|---:|
| 1 (all-intra) | 40.67 dB | 286k bits | 0.0 |
| 4 | 38.2 dB | 201k bits | 0.15 |
| 8 | 35.6 dB | 144k bits | 0.30 |
| 16 | 32.1 dB | 97k bits | 0.55 |

---

## Project Structure

```text
VideoLevel/
├─ benchmark/
│  ├─ sec1_quality.py           Quality benchmark (PSNR, SSIM)
│  ├─ sec2_capacity.py          Capacity sweep
│  ├─ sec3_methods.py           Method comparison (T1 vs LSB)
│  ├─ sec4_security.py          Steganalysis (chi, SPA, RS)
│  ├─ sec4_modern_detectors.py  WS, SPAM modern features
│  ├─ sec6_performance.py       Timing analysis
│  ├─ sec6_paper_summary.py     Paper-ready timing text
│  ├─ sec7_tradeoff.py          QP/GOP tradeoff recommendations
│  ├─ sec9_motion_gop.py        Motion-aware GOP selection
│  ├─ sec10_gop_sweep.py        Explicit GOP sweep
│  ├─ statistical_benchmark.py  Error bars (≥3 runs)
│  └─ sec1_audit.py             Quality guard audit logging
├─ circuits/                    Circom circuit + Groth16 keys
├─ data/
│  ├─ encoded/                  H.264 benchmark inputs
│  ├─ output/                   Stego outputs + sidecars
│  └─ raw/                      Raw source sequences
├─ src/
│  ├─ bitstream/                H.264 / CAVLC parsing and patching
│  ├─ core/
│  │  ├─ pipeline.py            IDR extraction
│  │  ├─ pipeline_optimized.py  Parallel/vec optimization
│  │  ├─ stego.py               Safety filter + embed logic
│  │  ├─ chaos.py               Arnold Cat + Logistic Map
│  │  └─ analysis_cache.py      Video analysis caching
│  ├─ manifest.py               v1.0.0 manifest schema
│  ├─ embedder.py               Public embed API
│  ├─ verifier.py               Public verify API
│  ├─ verifier_blind.py         Near-blind verification
│  └─ zk_proof.py               Proof packing + snarkjs bridge
├─ plan.md                      Paper-readiness tracking
└─ README.md
```

---

## Quick Start

### Requirements

- Python 3.12 recommended
- Node.js 14+
- `ffmpeg`
- Python packages from `requirements.txt`

Install:

```bash
py -3.12 -m pip install -r requirements.txt
cd circuits
npm install
cd ..
```

### Prepare input video

Use H.264 baseline with CAVLC:

```bash
ffmpeg -i input.y4m -c:v libx264 -profile:v baseline -coder 0 -g 1 -qp 22 -y output.h264
```

### Embed

```python
import os
from src.embedder import embed

secret_key = os.urandom(32)
chaos_key = b"example-chaos-key"
message = b"Hello ZK-Stego"

result = embed(
    video_path="data/encoded/foreman_cif_q22_g1.h264",
    message=message,
    output_path="data/output/stego.h264",
    circuits_dir="circuits",
    secret_key=secret_key,
    chaos_key=chaos_key,
)

print(result.bits_embedded, result.output_path)
# Also generates:
# - data/output/stego.h264.positions.json
# - data/output/stego.h264.meta.json
# - data/output/stego.h264.manifest.json (v1.0.0)
```

### Verify (standard mode)

```python
from src.verifier import verify

result = verify(
    stego_video_path="data/output/stego.h264",
    original_video_path="data/encoded/foreman_cif_q22_g1.h264",
    circuits_dir="circuits",
    secret_key=secret_key,
    message_length=len(message),
    chaos_key=chaos_key,
)

print(result.valid, result.message)
```

### Verify (near-blind mode)

Reduced dependency on cover video:

```python
from src.verifier_blind import verify_near_blind

result = verify_near_blind(
    stego_video_path="data/output/stego.h264",
    circuits_dir="circuits",
    secret_key=secret_key,
    message_length=len(message),
    chaos_key=chaos_key,
)
```

### Run tests

```bash
py -3.12 src/runtest/run_all.py
```

Expected: `32/32 passed`

### Run benchmarks

```bash
# Full benchmark suite
$env:SEC1_USE_REAL_PROOF_PIPELINE='1'
py -3.12 benchmark/safe_benchmark_runner.py

# Individual sections
py -3.12 benchmark/sec1_quality.py
py -3.12 benchmark/sec2_capacity.py
py -3.12 benchmark/sec4_security.py
py -3.12 benchmark/sec6_performance.py

# Statistical with error bars (IEEE-valid)
py -3.12 benchmark/statistical_benchmark.py --section sec1 --runs 3

# GOP sweep
py -3.12 benchmark/sec10_gop_sweep.py --sequences foreman_q22_g1
```

---

## How The Embedding Works

### Safety filter

`CAVLCSafetyFilter.get_safe_positions()` enforces:
1. Zero preservation
2. Trailing-ones protection
3. Bit-length invariance after CAVLC re-encode
4. Magnitude threshold
5. Non-patchable block exclusion
6. (Optional) FFmpeg pixel validation

### Bit-exact reconstruction

`BitstreamPatcher` re-encodes only the modified block and applies the patch only if the encoded bit length matches the original NAL slice region exactly.

### Manifest system

`StegoManifest` (v1.0.0) provides:
- Versioned schema for forward/backward compatibility
- Payload metadata (size, chaos expansion)
- Embedding metadata (strategy, positions count)
- Video metadata (file hash, codec, profile)
- Proof metadata (system, size, constraint count)
- Optional signing hooks for authentication

### Near-blind extraction

`verify_near_blind()` reduces cover dependency by:
1. Loading manifest.json for positions and metadata
2. Parsing stego video T1 coefficients directly
3. Extracting from specified positions
4. Verifying ZK proof

---

## Known Limits

- **Optimal Operating Mode:** GOP=1 / all-intra. GOP>1 support exists but degrades due to intra-prediction cascade.
- **Cold-start Cost:** IDR extraction dominates (~1500s per video). Cacheable after first run.
- **High QP Limits:** QP=32 assets have limited capacity under 40 dB guard.
- **Parser Resync Warnings:** Some streams emit warnings but still decode correctly.

---

## Paper-Ready Outputs

For IEEE TIP/TIFS submission:

1. **Quality** (SEC1): 11/11 sequences pass >40 dB frame-min guard
2. **Security** (SEC4): χ²=0.962, WS=0.85, SPAM=0.78 (all >α=0.05)
3. **Performance** (SEC6): 57s operational, 2.4s ZK prove
4. **Statistical** (statistical_benchmark.py): 3+ runs with mean±std
5. **Audit** (sec1_audit.py): Quality guard reason logs

---

## Rebuilding Circuit Artifacts

The repo already includes built artifacts. To rebuild:

```bash
cd circuits
npm run compile
npm run generate_proof_key
npm run generate_verification_key
```

---

## Documentation

### Project Documentation
- [`plan.md`](plan.md) — Paper-readiness tracking and roadmap
- [`COMPLETION.md`](COMPLETION.md) — Completion summary checklist
- [`OPERATING_ENVELOPE.md`](OPERATING_ENVELOPE.md) — Supported codec/GOP/QP ranges
- [`ARTIFACT_POLICY.md`](ARTIFACT_POLICY.md) — Cleanup and artifact management
- [`COMPARATIVE_ANALYSIS.md`](COMPARATIVE_ANALYSIS.md) — Comparison with existing systems

### Benchmark Documentation
- [`benchmark/sec1_quality.py`](benchmark/sec1_quality.py) — Quality benchmark
- [`benchmark/sec2_capacity.py`](benchmark/sec2_capacity.py) — Capacity analysis
- [`benchmark/sec3_methods.py`](benchmark/sec3_methods.py) — Method comparison
- [`benchmark/sec4_security.py`](benchmark/sec4_security.py) — Steganalysis
- [`benchmark/sec4_modern_detectors.py`](benchmark/sec4_modern_detectors.py) — WS/SPAM detectors
- [`benchmark/sec6_performance.py`](benchmark/sec6_performance.py) — Performance analysis
- [`benchmark/sec6_paper_summary.py`](benchmark/sec6_paper_summary.py) — Paper timing text
- [`benchmark/sec7_tradeoff.py`](benchmark/sec7_tradeoff.py) — QP/GOP tradeoff
- [`benchmark/sec10_gop_sweep.py`](benchmark/sec10_gop_sweep.py) — GOP sweep
- [`benchmark/statistical_benchmark.py`](benchmark/statistical_benchmark.py) — Error bars wrapper
- [`benchmark/sec1_audit.py`](benchmark/sec1_audit.py) — Quality guard audit logging

### API Documentation
- [`src/manifest.py`](src/manifest.py) — Manifest schema (v1.0.0)
- [`src/verifier_blind.py`](src/verifier_blind.py) — Near-blind verification
- [`src/verify_modes.py`](src/verify_modes.py) — Explicit verifier modes