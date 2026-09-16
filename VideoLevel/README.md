# Post-Quantum Lattice-Attested Video Steganography

Hide a fixed commitment to an ML-DSA-65 authenticated lattice sidecar inside H.264 Baseline/CAVLC video by modifying coefficients directly. The signature remains in a sidecar; neither uses SEI.

**Status:** Research prototype. The supported path is direct H.264 Baseline/CAVLC embedding with a signed lattice-attestation sidecar-assisted near-blind verification. The experimental in-tree lattice-ZKP prototype is disabled because it is not a reviewed, meaningful proof of the intended witness relation.
**Validated Runtime:** `py -3.12`
**Current hardening checks:** quick suite `23/23`, hardening `6/6`, and FFmpeg codec fixture `1/1` passed. Full local-asset E2E and benchmarks require revalidation after the circuit/sidecar update.
**Benchmark Sections:** SEC1-SEC10 (Quality, Capacity, Methods, Security, Performance, Tradeoff, Real-time, Motion/GOP, Statistical, Audit)

---

## Overview

The default system embeds a proof binding into H.264 bitstreams without leaving the compressed-domain workflow. It:

1. Generates an ML-DSA-65 signed receipt for the payload hash.
2. Stores it as `.lattice.json`.
3. Packs `[LQ1][4B message_length][message][32B sidecar commitment]` into the video.
4. Optionally applies chaos transforms:
   - Arnold Cat Map on payload bits
   - Logistic Map on embedding-position order
5. Locates CAVLC-safe candidate positions in IDR frames.
6. Applies length-preserving coefficient/sign modifications.
7. Reconstructs a valid H.264 bitstream.
8. Extracts the reference, verifies the ML-DSA signature and sidecar binding.

### New Features (IEEE-ready)

- **Authenticated Manifest Schema** (v2.0.0): Ed25519-signed sidecars bound to the stego asset and positions file
- **Near-Blind Verification**: Reduced cover dependency via sidecar-driven extraction
- **Statistical Benchmarking**: Multi-run error bars for IEEE TIP/TIFS validity (3+ runs)
- **Audit Logging**: SEC1 quality guard tracking with reason logs
- **Modern Detectors**: WS and SPAM steganalysis features
- **Optimized Extraction**: Parallel IDR parsing with vectorization
- **GOP Sweep Analysis**: Quality/capacity tradeoff across GOP=1,4,8,16

### Lattice attestation and payload format

The in-video payload is always `3 + 4 + message_length + 32` bytes. The 32-byte value is SHA3-256 over the exact lattice sidecar, so substituting a receipt or its ML-DSA signature fails verification.

ML-DSA-65 authenticates the payload hash and the manifest binds the final stego hash and positions hash. This is post-quantum authentication, not a zero-knowledge proof. Codec correctness remains covered by the direct-CAVLC implementation, hashes, signatures, FFmpeg fixtures, and integration tests.

The source tree retains an experimental Fiat-Shamir lattice preimage prototype for research-only testing. Public `embed()` and `verify()` reject `proof_backend="lattice_zkp"`; a reviewed lattice-ZK library/protocol with a verifier-known, non-trivial statement and an audited parameter set is required before enabling any lattice-ZKP path.

---

## Historic Benchmark Snapshot (not revalidated for this revision)

The figures below describe the previous locked `akiyo_q22_g1` artifact set.
They are retained for traceability only: the circuit constraint count and
near-blind sidecar trust contract have since changed. Do not use them as claims
for this revision until the benchmark suite is rerun with fresh signed v2
sidecars and the rebuilt circuit artifacts.

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
|-- circuits/                     Legacy Groth16 migration artifacts (not used by default)
|-- native/                       C17 Annex-B relay + optional x264 adapter
|-- data/
|   |-- encoded/                  Local H.264 benchmark inputs (ignored)
|   |-- output/                   Local stego outputs + sidecars (ignored)
|   `-- raw/                      Local raw source sequences (ignored)
|-- src/
|   |-- bitstream/                H.264 / CAVLC parsing and patching
|   |-- core/
|   |   |-- pipeline.py           IDR extraction
|   |   |-- pipeline_optimized.py Parallel/vec optimization
|   |   |-- stego.py              Safety filter + embed logic
|   |   |-- chaos.py              Arnold Cat + Logistic Map
|   |   `-- analysis_cache.py     Process-local safe video-analysis cache
|   |-- manifest.py               v4.0.0 ML-DSA-authenticated manifest schema
|   |-- embedder.py               Public embed API
|   |-- verifier.py               Public verify API
|   |-- verifier_blind.py         Near-blind verification
|   |-- lattice_pq.py             ML-KEM/ML-DSA + transparent lattice-ZKP sidecar
|   `-- zk_proof.py               Legacy Groth16 migration bridge
|-- plan.md                       Current freeze plan
`-- README.md
```

---

## Quick Start

### Requirements

- Python 3.12 recommended
- `ffmpeg` 8.x or compatible
- Python packages from `requirements.lock`

Current audited Python package set:

- `numpy` 2.2.6
- `matplotlib` 3.10.8
- `scipy` 1.17.0
- `scikit-image` 0.26.0
- `cryptography` 46.0.5

Observed native toolchain on the current audit machine:

- Python 3.12.10
- `ffmpeg` 8.0.1

Install:

```bash
py -3.12 -m pip install -r requirements.lock
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
from src.lattice_pq import LatticeSigner

witness_key = os.urandom(32)
chaos_key = b"example-chaos-key"
message = b"Hello ZK-Stego"
lattice_public_key, lattice_private_key = LatticeSigner.generate_keypair()

result = embed(
    video_path="data/encoded/foreman_cif_q22_g1.h264",
    message=message,
    output_path="data/output/stego.h264",
    circuits_dir="",  # unused by the default lattice_zkp backend
    secret_key=witness_key,
    chaos_key=chaos_key,
    lattice_private_key=lattice_private_key,
    manifest_signer_id="example-sender-v1",
)

print(result.bits_embedded, result.output_path)
# Also generates:
# - data/output/stego.h264.positions.json
# - data/output/stego.h264.meta.json
# - data/output/stego.h264.lattice.json (ML-DSA-65 receipt)
# - data/output/stego.h264.manifest.json (v4.0.0, ML-DSA-65-signed)
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
    circuits_dir="",
    secret_key=bytes(range(32)),
    lattice_private_key=lattice_private_key,
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
    circuits_dir="",
    secret_key=b"",  # unused by lattice-attestation verification
    lattice_public_key=lattice_public_key,
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
- the 1952-byte ML-DSA-65 public key of the manifest signer

```python
from src.verifier_blind import verify_near_blind

# Reuse the public key returned by LatticeSigner.generate_keypair() at embed time.
manifest_public_key = lattice_public_key

result = verify_near_blind(
    stego_video_path="data/output/stego.h264",
    circuits_dir="",
    secret_key=b"",  # unused by the active lattice-attestation path
    message_length=len(message),
    chaos_key=chaos_key,
    manifest_public_key=manifest_public_key,
)
```

### Verifier modes

- `verify()`:
  - strict non-blind verification
  - requires the original cover video or equivalent precomputed operating positions
- `verify_near_blind()`:
  - sidecar-assisted near-blind verification
  - does not require the original cover video
  - requires a signed manifest binding the stego hash and positions-sidecar hash
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

The demo verifies the current locked operating artifact through the public
`verify()` API. It exits with code `2` when no verified locked SEC1 operating
contract is currently available.

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

# Upgrade-v2 trust architecture diagnostics, claim gates, and product-readiness gates
py -3.12 -m benchmark.safe_benchmark_runner --sections 44 45 46

# Product-readiness JSON only
py -3.12 -m benchmark.sec46_product_readiness

# Validate the trust corpus promotion contract
py -3.12 -m benchmark.trust_corpus

# Print a ready-to-paste external corpus manifest entry
py -3.12 -m benchmark.trust_corpus register-file --id sample-001 --path data/external/trust_corpus/sample_001.h264 --source-uri https://example.org/dataset --license CC-BY-4.0 --codec h264 --container raw_h264 --frame-count 300 --resolution 352x288 --source "Example Dataset"
```

Upgrade-v2 application-level trust workflows are exposed through
`src.trust.workflows` for provenance anchoring, fingerprint registry lookup,
watermark receipt, and model/device attestation.
Every workflow output includes a versioned `schema` and `workflow` field, with
validators in `src.trust.workflow_contracts`.

CLI usage:

```bash
py -3.12 -m src.trust.workflows provenance --manifest manifest.json --registry-uri registry://example/asset --registry-out provenance_registry.json --output provenance.json
py -3.12 -m src.trust.workflows fingerprint --frames frames.npy --records registry.json --threshold 0 --output fingerprint.json
py -3.12 -m src.trust.workflows watermark --frames embedded.npy --key demo-key --frame-shape 64 64 --threshold 0.5 --output watermark.json
py -3.12 -m src.trust.workflows attestation --signer-key demo-key --video-path video.bin --model-config-path model.json --model-binary-path model.bin --policy-id policy-v1 --timestamp 2026-06-09T00:00:00Z --output attestation.json
py -3.12 -m src.trust.workflows attestation --signer-scheme ed25519 --signer-key demo-seed --video-path video.bin --model-config-path model.json --model-binary-path model.bin --policy-id policy-v1 --timestamp 2026-06-09T00:00:00Z --output attestation_ed25519.json
```

Section `46` is the product-readiness source of truth. Current state:

- `seed_surface_ready=true`.
- `all_product_ready=false`.
- `product_ready`: C2PA-style local root-anchor registry, local fingerprint-registry lookup receipts, controlled watermark receipt replay, and workflow API/CLI.
- `product_seed`: none.
- `prototype`: software attestation, toy ZK receipt circuits.
- `blocked`: ZKML model binding.

`benchmark.trust_corpus` currently validates a two-file external CC0 seed
corpus. It is enough for seed-scope evidence, but broad-public-dataset claims
remain blocked until a larger external corpus with source, license, file
metadata, and matching hashes is registered.
See `doc/trust_corpus_onboarding.md` for the step-by-step corpus playbook.

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

`StegoManifest` (v2.0.0) provides:
- Versioned schema for forward/backward compatibility
- Payload metadata (size, chaos expansion)
- Embedding metadata (strategy, positions count)
- Original-cover and stego-file hashes
- Canonical positions-sidecar hash
- Proof metadata (system, size, constraint count)
- Required Ed25519 authentication for near-blind verification

### Near-blind extraction

`verify_near_blind()` reduces cover dependency by:
1. Verifying the Ed25519 manifest and its stego/positions hashes
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
- **Upgrade-v2 Product Scope:** trust-plane seed surfaces are usable for local workflows, but section `46` currently blocks full-product claims for robust watermarking, hardware TEE attestation, broad public fingerprint robustness, full C2PA compliance, and ZKML model binding.
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

Circuit artifacts are deliberately not committed. Rebuild them from a verified
Powers-of-Tau file and freshly generated secret entropy. The build writes
checksums to `build/artifacts.json`.

```bash
cd circuits
npm ci
export PTAU_FILE=/absolute/path/to/verified.ptau
export ZKEY_ENTROPY="fresh-secret-entropy-at-least-32-characters"
npm run build
npm run verify-artifacts
```

---

## Documentation

### Project Documentation
- [`plan.md`](plan.md) - Paper-readiness tracking and roadmap
- [`system.txt`](system.txt) - Plain-text current-system design summary
- [`PAPER_EVIDENCE.md`](PAPER_EVIDENCE.md) - Claim-to-evidence staging notes
- [`COMPLETION.md`](COMPLETION.md) - Completion summary checklist
- [`OPERATING_ENVELOPE.md`](OPERATING_ENVELOPE.md) - Supported codec/GOP/QP ranges
- [`REALTIME.md`](REALTIME.md) - Live Annex-B transport contract and native-backend boundary
- [`native/README.md`](native/README.md) - C17 build, relay, and selected x264 profile
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
- [`src/manifest.py`](src/manifest.py) - Authenticated manifest schema (v2.0.0)
- [`src/verifier_blind.py`](src/verifier_blind.py) - Near-blind verification
- [`src/verify_modes.py`](src/verify_modes.py) - Explicit verifier modes
