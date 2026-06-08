# ZK-SNARK Video Steganography

Hide a Groth16 zero-knowledge proof inside H.264 baseline video by modifying CAVLC coefficients in IDR frames.

**Status:** Research prototype with a frozen benchmark-grade core: locked operating-point embedding plus sidecar-assisted near-blind verification
**Validated Runtime:** `py -3.12`
**Tests:** full suite executes `35/35` passing checks with `0` failed and `0` skipped
**Benchmark Sections:** SEC1-SEC10 (Quality, Capacity, Methods, Security, Performance, Tradeoff, Real-time, Motion/GOP, Statistical, Audit)

---

## Overview

The system embeds a message-authentication proof into H.264 bitstreams without leaving the compressed-domain workflow. It:

1. Generates a Groth16 proof for the payload.
2. Packs `[4B message_length][message][129B compressed proof]`.
3. Optionally applies chaos transforms:
   - Arnold Cat Map on payload bits
   - Logistic Map on embedding-position order
4. Locates CAVLC-safe candidate positions in IDR frames.
5. Applies length-preserving coefficient/sign modifications.
6. Reconstructs a valid H.264 bitstream.
7. Extracts and verifies the proof from the stego video.

### New Features (IEEE-ready)

- **Versioned Manifest Schema** (v1.0.0): Structured sidecar files with signing hooks
- **Near-Blind Verification**: Reduced cover dependency via sidecar-driven extraction
- **Statistical Benchmarking**: Multi-run error bars for IEEE TIP/TIFS validity (3+ runs)
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

Current paper-grade artifacts were refreshed on `2026-06-08` for the locked
`akiyo_q22_g1` operating point and validated with:

```bash
py -3.12 src/runtest/run_all.py
py -3.12 -m benchmark.safe_benchmark_runner --sections 1 2 3 4 5 6
```

### SEC1: Quality At The Locked 1232-bit Operating Point

| Sequence | Full-video PSNR | Min Modified-Frame PSNR | Avg SSIM | Embedded bits | Verify |
|---|---:|---:|---:|---:|---:|
| Akiyo QP22 G1 | 53.01 dB | 40.30 dB | 0.9997 | 1232/1232 | true |

The current frozen paper-grade baseline is a single verified operating
contract, not a claim that every listed asset has the same fully verified
contract.

### SEC2: Capacity

SEC2 uses layered capacity accounting from the live `akiyo_q22_g1` artifact:

| Term | Bits |
|---|---:|
| `raw_safe_bits` | 413415 |
| `patchable_usable_bits` | 2000 |
| `validated_pool_bits` | 1449 |
| `operating_bits` | 1232 |
| `zk_blob_bits` | 1232 |

PSNR sweep at the locked operating point:

| Fraction | Bits | PSNR |
|---:|---:|---:|
| 25% | 304 | 56.99 dB |
| 50% | 616 | 54.89 dB |
| 75% | 920 | 53.58 dB |
| 100% | 1232 | 52.31 dB |

Do not collapse raw, patchable, validated, operating, and applied capacity into
one headline number.

### SEC4: Steganalysis

Current committed SEC4 artifact (`benchmark/results/sec4_security_data.json`) records:
- chi-square p-value at operating point: `0.9622`
- SPA at operating point: `0.03762`
- RS delta: `0.0` (inapplicable to H.264 CAVLC)

### SEC5: ZKP Overhead

Current committed SEC5 artifact (`benchmark/results/sec5_zkp_data.json`) records:
- **Groth16 packed proof-bearing payload**: `147 B`
- **Groth16 prove time**: `1556.58 ms`
- **Groth16 verify time**: `8.5 ms`
- Alternative systems remain much larger or slower in the committed comparison artifact

### SEC6: Performance

Current committed SEC6 artifact (`benchmark/results/sec6_performance_data.json`) records for `akiyo_q22_g1`:
- **Pre-processing** (one-time, cacheable): `59.0s`
- **Operational cost** (public embed + verify path): `26.1s`
- **Total end-to-end time**: `85.0s`
- **Standalone ZK prove line item**: `0.0s` because proof generation is included inside the combined public embed stage
- **ZK verify time**: `3.83s`

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
|-- benchmark/
|   |-- sec1_quality.py           Quality benchmark (PSNR, SSIM)
|   |-- sec2_capacity.py          Capacity sweep
|   |-- sec3_methods.py           Method comparison (T1 vs LSB)
|   |-- sec4_security.py          Steganalysis (chi, SPA, RS)
|   |-- sec4_modern_detectors.py  WS, SPAM modern features
|   |-- sec6_performance.py       Timing analysis
|   |-- sec6_paper_summary.py     Paper-ready timing text
|   |-- sec7_tradeoff.py          QP/GOP tradeoff recommendations
|   |-- sec9_motion_gop.py        Motion-aware GOP selection
|   |-- sec10_gop_sweep.py        Explicit GOP sweep
|   |-- statistical_benchmark.py  Error bars, 3 or more runs
|   `-- sec1_audit.py             Quality guard audit logging
|-- circuits/                     Circom circuit + Groth16 keys
|-- data/
|   |-- encoded/                  H.264 benchmark inputs
|   |-- output/                   Stego outputs + sidecars
|   `-- raw/                      Raw source sequences
|-- src/
|   |-- bitstream/                H.264 / CAVLC parsing and patching
|   |-- core/
|   |   |-- pipeline.py           IDR extraction
|   |   |-- pipeline_optimized.py Parallel/vec optimization
|   |   |-- stego.py              Safety filter + embed logic
|   |   |-- chaos.py              Arnold Cat + Logistic Map
|   |   `-- analysis_cache.py     Video analysis caching
|   |-- manifest.py               v1.0.0 manifest schema
|   |-- embedder.py               Public embed API
|   |-- verifier.py               Public verify API
|   |-- verifier_blind.py         Near-blind verification
|   `-- zk_proof.py               Proof packing + snarkjs bridge
|-- plan.md                       Current freeze plan
`-- README.md
```

---

## Quick Start

### Requirements

- Python 3.12 recommended
- Node.js 22.x or compatible
- `circom` 2.2.x
- `snarkjs` 0.7.x
- `ffmpeg` 8.x or compatible
- Python packages from `requirements.txt`

Current audited Python package set:

- `numpy` 2.2.6
- `matplotlib` 3.10.8
- `scipy` 1.17.0
- `scikit-image` 0.26.0
- `cryptography` 46.0.5

Observed native toolchain on the current audit machine:

- Python 3.12.10
- Node.js 22.20.0
- `circom` 2.2.0
- `snarkjs` 0.7.6
- `ffmpeg` 8.0.1

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

### Embed (locked operating-point mode)

When reproducing a benchmark-grade operating point, the API can reuse a
pre-validated operating-position set directly:

```python
from src.embedder import embed

result = embed(
    video_path="data/encoded/coastguard_cif_q22_g1.h264",
    message=b"ZK-bench-v1.0!",
    output_path="data/output/stego_locked.h264",
    circuits_dir="circuits",
    secret_key=bytes(range(32)),
    chaos_key=b"sec1_benchmark_chaos_v1",
    precomputed_positions=locked_positions,
    trust_precomputed_positions=True,
)
```

This mode is intended for locked benchmark operating points that have already
been validated end-to-end.

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

Reduced dependency on the original cover video. This mode requires:
- `manifest.json`
- `positions.json`
- a stego asset whose stored operating positions are still valid after reconstruction

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

### Verifier modes

- `verify()`:
  - strict non-blind verification
  - requires the original cover video or equivalent precomputed operating positions
- `verify_near_blind()`:
  - sidecar-assisted near-blind verification
  - does not require the original cover video
  - still requires sidecar metadata such as `manifest.json` and `positions.json`
- blind-core verification:
  - currently experimental / research-only
  - not part of the frozen benchmark-grade core path
  - should be treated as future work in the current paper

### Run tests

```bash
py -3.12 src/runtest/run_all.py --quick
py -3.12 src/runtest/test_phase4_reconstruct.py
py -3.12 src/runtest/test_phase5_extract_verify.py
py -3.12 src/runtest/test_phase6_near_blind_manifest.py
py -3.12 src/runtest/test_phase7_regression_cases.py
py -3.12 src/runtest/run_all.py
```

Test exit codes:

- `0`: all selected tests passed.
- `1`: at least one selected test failed.
- `2`: no assertion failed, but at least one required case was skipped, so the
  phase is incomplete and must not be counted as full evidence.

### Run minimal API demo

```bash
py -3.12 src/runtest/demo_embed_verify.py
```

The demo uses the real `embed()` and `verify()` APIs. It exits with code `2`
when no verified locked SEC1 operating contract is currently available.

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

# Upgrade-v2 trust architecture diagnostics and claim-gated evidence
py -3.12 -m benchmark.safe_benchmark_runner --sections 44 45
```

Upgrade-v2 application-level trust workflows are exposed through
`src.trust.workflows` for provenance anchoring, fingerprint registry lookup,
watermark receipt, and model/device attestation.

CLI usage:

```bash
py -3.12 -m src.trust.workflows provenance --manifest manifest.json --registry-uri registry://example/asset --output provenance.json
py -3.12 -m src.trust.workflows fingerprint --frames frames.npy --records registry.json --threshold 0 --output fingerprint.json
py -3.12 -m src.trust.workflows watermark --frames embedded.npy --key demo-key --frame-shape 64 64 --threshold 0.5 --output watermark.json
py -3.12 -m src.trust.workflows attestation --signer-key demo-key --video-path video.bin --model-config-path model.json --model-binary-path model.bin --policy-id policy-v1 --timestamp 2026-06-09T00:00:00Z --output attestation.json
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
1. Loading `manifest.json` / `positions.json`
2. Rebuilding extraction offsets from the stego bitstream
3. Extracting from the stored operating positions
4. Verifying the ZK proof

### Threat model summary

- Sender knows:
  - the original cover video
  - the embedding key material
  - the proof-generation inputs
- Strict verifier knows:
  - the stego video
  - the original cover video or locked operating positions
  - the verification key material
- Sidecar-assisted near-blind verifier knows:
  - the stego video
  - authenticated sidecar metadata
  - the verification key material
- Passive observer / attacker is assumed to see:
  - the stego video
  - any public stream metadata
  - but not the secret embedding / verification keys

---

## Known Limits

- **Optimal Operating Mode:** GOP=1 / all-intra. GOP>1 support exists but degrades due to intra-prediction cascade.
- **Cold-start Cost:** IDR extraction dominates (~1500s per video). Cacheable after first run.
- **Capacity Reporting:** raw safe-position counts are not the same as final patchable or quality-validated operating capacity.
- **Locked Operating-Point Mode:** the strongest end-to-end path currently reuses pre-validated operating positions for selected benchmark assets.
- **Broad Public API Mode:** generic embedding without locked operating positions still under-fills on representative assets and should not be used for headline claims.
- **Blind-Core Branch:** candidate synchronization and proxy research exists, but blind extraction is not yet a usable system feature and should be treated as future work.
- **High QP Limits:** QP=32 assets have limited capacity under 40 dB guard.
- **Parser Resync Warnings:** Some streams emit warnings but still decode correctly.

---

## Paper-Ready Outputs

For IEEE TIP/TIFS submission:

1. **Quality** (SEC1): locked `akiyo_q22_g1` contract embeds `1232/1232` bits with `53.01 dB` full-video PSNR and `40.30 dB` minimum modified-frame PSNR
2. **Security** (SEC4): chi-square p-value `0.9622`, SPA `0.03762`, RS `0.0` at operating point
3. **ZKP Overhead** (SEC5): current committed artifact reports 147 B packed Groth16 payload, 1556.58 ms prove, 8.5 ms verify
4. **Performance** (SEC6): current committed artifact reports 59.0s pre-processing, 26.1s operational, 85.0s total on `akiyo_q22_g1`
5. **Statistical** (statistical_benchmark.py): 3+ runs with mean/std
6. **Audit** (sec1_audit.py): Quality guard reason logs

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
- [`plan.md`](plan.md) - Paper-readiness tracking and roadmap
- [`system.txt`](system.txt) - Plain-text current-system design summary
- [`PAPER_EVIDENCE.md`](PAPER_EVIDENCE.md) - Claim-to-evidence staging notes
- [`COMPLETION.md`](COMPLETION.md) - Completion summary checklist
- [`OPERATING_ENVELOPE.md`](OPERATING_ENVELOPE.md) - Supported codec/GOP/QP ranges
- [`ARTIFACT_POLICY.md`](ARTIFACT_POLICY.md) - Cleanup and artifact management
- [`COMPARATIVE_ANALYSIS.md`](COMPARATIVE_ANALYSIS.md) - Comparison with existing systems
- [`doc/system_video_embedding_walkthrough.tex`](doc/system_video_embedding_walkthrough.tex) - Detailed Vietnamese system walkthrough

### Benchmark Documentation
- [`benchmark/sec1_quality.py`](benchmark/sec1_quality.py) - Quality benchmark
- [`benchmark/sec2_capacity.py`](benchmark/sec2_capacity.py) - Capacity analysis
- [`benchmark/sec3_methods.py`](benchmark/sec3_methods.py) - Method comparison
- [`benchmark/sec4_security.py`](benchmark/sec4_security.py) - Steganalysis
- [`benchmark/sec4_modern_detectors.py`](benchmark/sec4_modern_detectors.py) - WS/SPAM detectors
- [`benchmark/sec6_performance.py`](benchmark/sec6_performance.py) - Performance analysis
- [`benchmark/sec6_paper_summary.py`](benchmark/sec6_paper_summary.py) - Paper timing text
- [`benchmark/sec7_tradeoff.py`](benchmark/sec7_tradeoff.py) - QP/GOP tradeoff
- [`benchmark/sec10_gop_sweep.py`](benchmark/sec10_gop_sweep.py) - GOP sweep
- [`benchmark/statistical_benchmark.py`](benchmark/statistical_benchmark.py) - Error bars wrapper
- [`benchmark/sec1_audit.py`](benchmark/sec1_audit.py) - Quality guard audit logging

### API Documentation
- [`src/manifest.py`](src/manifest.py) - Manifest schema (v1.0.0)
- [`src/verifier_blind.py`](src/verifier_blind.py) - Near-blind verification
- [`src/verify_modes.py`](src/verify_modes.py) - Explicit verifier modes
