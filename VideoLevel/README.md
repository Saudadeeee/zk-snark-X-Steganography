# Post-Quantum Lattice Zero-Knowledge Video Steganography

Embed a **lattice zero-knowledge proof** directly inside an H.264 video and
verify it **from the stego video alone** — no sidecar, no SEI box, no access to
the cover. The proof is a BDLOP commitment with a Fiat–Shamir-with-aborts proof
of knowledge of its opening, bound to the carrier-normalized stream, a one-use
verifier session challenge and an ML-DSA-65-signed relation registry. It is
post-quantum (lattice M-SIS/M-LWE) and self-implemented from the published
protocol (Baum et al., SCN 2018); **unaudited**, a research prototype.

**Status (2026-10-26):** production parameter set `bdlop-open-128-v3`
(binding 172/156, hiding 164/150 bit core-SVP). Unit suite **1217 passed /
123 skipped**; full-system end-to-end check **8/8 modes** verify from the video
and reject replay + tamper. The paper (`docs/paper/main.pdf`, 28 pp.) builds
clean. Code: `src/lattice_zk/`, `src/transport/`, `src/registry/`.

**Runtime:** Python 3.12, `ffmpeg` 8.x, packages in `requirements.lock`.

> A large **pre-lattice-ZK** subsystem (ML-DSA sidecar attestation, the
> SEC1–SEC10 benchmark suite, Groth16 circuits, near-blind manifest API) is kept
> under `src/legacy/`, `benchmark/legacy/`, `legacy/` and documented from
> "Historic Benchmark Snapshot" onward in this file **for traceability only**.
> It is not the current system; read the map below first.

## What to read to understand the system

In order, shortest path first:

1. [`docs/handoff/`](docs/handoff/README.md) — maintainer onboarding (Vietnamese):
   overview → architecture → theory → operations → results → limitations.
   Start here.
2. [`docs/LATTICE_ZK_BDLOP_SPEC.md`](docs/LATTICE_ZK_BDLOP_SPEC.md) — the
   authoritative protocol spec and security argument (parameters, envelope,
   statement, offline epochs).
3. Feature docs, as needed:
   [`docs/CARRIERS_VA_CHUNKING.md`](docs/CARRIERS_VA_CHUNKING.md) (carrier
   selection + ZKBC transport), [`docs/GOP_HD_SUPPORT.md`](docs/GOP_HD_SUPPORT.md)
   (GOP>1 / HD), [`docs/CABAC_SUPPORT.md`](docs/CABAC_SUPPORT.md) (H.264
   Main/High), [`docs/ROBUST_MODE.md`](docs/ROBUST_MODE.md) (semi-fragile
   survive-transcode mode), [`docs/PROOF_NHI_PHAN_VA_KHOANG.md`](docs/PROOF_NHI_PHAN_VA_KHOANG.md)
   (binary / payload-range proofs).
4. [`docs/paper/main.pdf`](docs/paper/main.tex) — the write-up; the external
   cryptographer review package is [`docs/review/`](docs/review/README.md).
5. Decision records (optional):
   [`docs/LATTICE_ZK_BDLOP_PLAN.md`](docs/LATTICE_ZK_BDLOP_PLAN.md),
   [`docs/LATTICE_BACKEND_SURVEY.md`](docs/LATTICE_BACKEND_SURVEY.md),
   [`docs/ROADMAP.md`](docs/ROADMAP.md).

Two browser aids: [`site/`](site/README.md) is a multi-page explainer for
non-technical readers; [`webdemo/`](webdemo/README.md) runs the real lattice
math in the browser.

## Quick start (current CLI)

The production interface is `python -m src.lattice_zk.cli` (role-separated:
issuer / holder / verifier). The verifier works from the stego video, the signed
registry, the issuer key, its session database and a shared hex sync key in
`ZKSTEGO_LATTICEZK_SYNC_KEY_HEX`.

```bash
python -m src.lattice_zk.cli --help                 # all subcommands
python -m src.lattice_zk.cli issuer-keygen  --public i.pub --private i.key
python -m src.lattice_zk.cli credential-new --payload-file dev.bin --public c.pub.json --private c.key.json
python -m src.lattice_zk.cli registry-sign  --issuer-private i.key --epoch 1 --credential c.pub.json --out r.json
# session-issue -> embed -> verify; see docs/handoff/04_van_hanh.md for the full flow.
```

`--codec-policy {v1,v2,cabac}` selects the digest/codec scope (`v2` default;
`cabac` for H.264 Main/High), `--gop-policy` handles GOP>1 streams,
`--adaptive-chunks` the capacity-adaptive transport, `--payload-range-bytes`
attaches a payload range proof, `--epoch-beacon` enables offline verification.
The semi-fragile robust mode has its own CLI, `python -m src.robust.cli`.

### Reproducing the evaluation

[`ARTIFACT.md`](ARTIFACT.md) lists the data (Xiph URLs + SHA-256), encoder
settings, scripts, run times and which result file each paper table comes from.
Each script has a `.sh` and a `.ps1` version:

```bash
sh scripts/run_unit_tests.sh      # lattice-ZK + touched-module tests, no data (~90 s)
sh scripts/prepare_data.sh        # verify/download Y4M sources, encode covers
sh scripts/reproduce_small.sh     # one registered E2E on a 100-frame cut (~10-15 min)
sh scripts/reproduce_all.sh       # full sweep and report generation (tens of hours)
```

CI (`.github/workflows/videolevel-latticezk.yml`) runs the unit-test script on
Ubuntu with Python 3.12.

---

# Historical (pre-lattice-ZK subsystem) — kept for traceability

Everything from here down describes the earlier ML-DSA-sidecar system and its
SEC1–SEC10 benchmark suite, before the lattice-ZK video proof above became the
system. The commands reference `src/legacy/` and `benchmark/legacy/`, and many
figures predate the current parameter set. Do not read this to understand the
current system; use the map above.

## Historic Benchmark Snapshot (not revalidated for this revision)

The figures below describe the previous locked `akiyo_q22_g1` artifact set.
They are retained for traceability only: the circuit constraint count and
near-blind sidecar trust contract have since changed. Do not use them as claims
for this revision until the benchmark suite is rerun with fresh signed v2
sidecars and the rebuilt circuit artifacts.

The legacy SEC1-SEC10 benchmark suite (`safe_benchmark_runner.py` and the
`secN_*.py` scripts) was moved to `benchmark/legacy/` in the October 2026 layout
cleanup, and most of its scripts were then removed; among the SEC scripts only
`benchmark/legacy/sec4_security.py` and `benchmark/legacy/sec5_zkp.py` remain.
The current evaluation is the lattice-ZK suite described in
[`ARTIFACT.md`](ARTIFACT.md) (`scripts/repro.py`, `benchmark/latticezk_*`). The full move/delete map is in
the October 2026 cleanup commits (git history). The command lines and result-file citations in the legacy sections below
are kept for traceability and name scripts or result files that were moved or
removed by that cleanup (for example `benchmark/results/sec4_security_data.json`,
`sec5_zkp_data.json` and `sec6_performance_data.json` were removed).

```bash
py -3.12 src/runtest/run_all.py
# legacy SEC runner benchmark/safe_benchmark_runner.py was removed in the Oct 2026 cleanup
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

The historical SEC5 artifact (`benchmark/results/sec5_zkp_data.json`) is retained,
but must not be used for conclusions: it labels an ECDSA signature as
"ZK-Schnorr", reports a packed payload as proof size, and hard-codes Groth16
verification time to `8.5 ms`. The corrected script separates the ECDSA
signature baseline from ZKP systems, measures Groth16 end-to-end bridge wall
time, and writes new artifacts without overwriting history:

```powershell
py -3.12 benchmark/legacy/sec5_zkp.py --force
```

Outputs are `benchmark/results/sec5_zkp_data_new.json`,
`sec5_proof_size_new.png`, `sec5_timing_new.png`, and
`sec5_properties_heatmap_new.png`. PLONK/STARK/Bulletproof values remain
explicitly marked illustrative literature estimates, not same-machine
measurements; they are not fair quantitative comparisons. Groth16 is a
comparison baseline, not the current lattice proof system. ECDSA is an
authentication signature and does not provide zero knowledge.

Corrected run on this development machine (three Groth16 trials, 50 ECDSA
trials): Groth16 proof `129 B`, packed proof-bearing payload `147 B`, mean
prove `7042.44 ms`, and mean verify `2208.23 ms` including bridge/subprocess
overhead. ECDSA mean signature size was `70.88 B`, signing `0.623 ms`, and
verification `0.256 ms`; those signature timings are not a ZKP comparison.
These measurements are implementation- and machine-specific, and Groth16 is
not evidence for the lattice proof's performance or security.

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

The layout below reflects the October 2026 cleanup (the full move/delete map is
in the October 2026 cleanup commits in git history). The pre-lattice-ZK
embed/verify stack moved under `src/legacy/`, the
transport and registry modules into `src/transport/` and `src/registry/`, and
the Groth16 circuits, native relay and LaZer container under `legacy/`.

```text
VideoLevel/
|-- src/
|   |-- lattice_zk/      BDLOP commitment, opening/equality/linkage proofs, video statement, CLI
|   |-- transport/       blind carrier sync, chunk framing, GOP policy, canonical digest
|   |-- registry/        relation registry (zkp_registry), verifier sessions, HTTP front end, ML-DSA/ML-KEM (lattice_pq)
|   |-- core/            carrier analysis, cost model, CAVLC embed/order, analysis cache
|   |-- bitstream/       H.264 / CAVLC parsing and patching
|   |-- legacy/          pre-lattice-ZK embed/verify, Groth16 bridge, trust/provenance, realtime
|   |-- runtest/         current tests; runtest/legacy/ for legacy-module tests
|   `-- exceptions.py
|-- benchmark/           latticezk_* drivers + case files + results/; legacy/ holds the old SEC1-SEC10 suite
|-- research/bdlop_params/  core-SVP parameter estimates, KAT v1/v2, cross-checks
|-- scripts/             repro.py and its .sh/.ps1 wrappers; ops/ operational run scripts
|-- legacy/              circuits/ (Groth16), native/ (x264 fork + C relay), lazer/ (container)
|-- docs/                design docs, paper/, review/; legacy/ for old root docs
|-- data/                local raw/encoded/output trees (gitignored)
|-- ARTIFACT.md
`-- README.md
```

---

## Quick Start

### Requirements

- Python 3.12 recommended
- `ffmpeg` 8.x or compatible
- Python packages from `requirements.lock`

Current locked Python package set (`requirements.lock`, 2026-10-21):

- `numpy` 2.5.3
- `matplotlib` 3.11.2
- `scipy` 1.18.1
- `scikit-image` 0.26.0
- `scikit-learn` 1.7.2
- `cryptography` 50.0.1
- `pqcrypto` 1.0.0, `psutil` 7.2.2, `pytest` 9.1.1

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
from src.legacy import embed
from src.registry.lattice_pq import LatticeSigner

witness_key = os.urandom(32)
chaos_key = b"example-chaos-key"
message = b"Hello ZK-Stego"
lattice_public_key, lattice_private_key = LatticeSigner.generate_keypair()

result = embed(
    video_path="data/encoded/foreman_cif_q22_g1.h264",
    message=message,
    output_path="data/output/stego.h264",
    circuits_dir="",  # legacy compatibility argument; no ZKP backend is enabled
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
# - data/output/stego.h264.pq-statement.json (only when an issuer-verified registered LaZer relation and private opening are supplied; not a proof)
# - data/output/stego.h264.manifest.json (v4.0.0, ML-DSA-65-signed)
```

### Embed (locked operating-point mode)

When reproducing a benchmark-grade operating point, the API can reuse a
pre-validated operating-position set directly:

```python
from src.legacy import embed

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
from src.legacy import verify

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
from src.legacy import verify_near_blind

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
py -3.12 src/runtest/legacy/test_phase5_extract_verify.py
py -3.12 src/runtest/legacy/test_phase6_near_blind_manifest.py
py -3.12 src/runtest/legacy/test_phase7_regression_cases.py
py -3.12 src/runtest/run_all.py
```

Test exit codes:

- `0`: all selected tests passed.
- `1`: at least one selected test failed.
- `2`: no assertion failed, but at least one required case was skipped, so the
  phase is incomplete and must not be counted as full evidence.

### Run minimal API demo

The standalone `demo_embed_verify.py` script was removed in the October 2026
layout cleanup. The legacy public embed/verify API it exercised now lives in
`src.legacy` (`from src.legacy import embed, verify, verify_near_blind`); its
tests are under `src/runtest/legacy/`. See the October 2026 cleanup commits.

### Run benchmarks

These are the legacy SEC1-SEC10 commands. Per the October 2026 cleanup,
`safe_benchmark_runner.py`, `sec1_quality.py`, `sec2_capacity.py`,
`sec6_performance.py`, `statistical_benchmark.py`, `sec10_gop_sweep.py` and
`sec46_product_readiness.py` were removed; `sec4_security.py`,
`lattice_in_video_feasibility` and `trust_corpus` moved under `benchmark/legacy/`
(module path `benchmark.legacy.*`). They are retained here for traceability; the
current evaluation path is `scripts/repro.py` / `benchmark/latticezk_*` (see
[`ARTIFACT.md`](ARTIFACT.md)).

```bash
# Full benchmark suite
$env:SEC1_USE_REAL_PROOF_PIPELINE='1'
py -3.12 benchmark/safe_benchmark_runner.py   # removed in the Oct 2026 cleanup

# Individual sections
py -3.12 benchmark/sec1_quality.py
py -3.12 benchmark/sec2_capacity.py
py -3.12 benchmark/legacy/sec4_security.py
py -3.12 benchmark/sec6_performance.py       # removed in the Oct 2026 cleanup

# Compare actual proof bytes with measured capacity for one video/configuration
py -3.12 -m benchmark.legacy.lattice_in_video_feasibility --proof-artifact path/to/proof.bin --capacity-bits 1232 --framing-bytes 16

# Statistical with error bars (IEEE-valid)
py -3.12 benchmark/statistical_benchmark.py --section sec1 --runs 3

# GOP sweep
py -3.12 benchmark/sec10_gop_sweep.py --sequences foreman_q22_g1

# Upgrade-v2 trust architecture diagnostics, claim gates, and product-readiness gates
py -3.12 -m benchmark.safe_benchmark_runner --sections 44 45 46

# Product-readiness JSON only
py -3.12 -m benchmark.sec46_product_readiness

# Validate the trust corpus promotion contract
py -3.12 -m benchmark.legacy.trust_corpus

# Print a ready-to-paste external corpus manifest entry
py -3.12 -m benchmark.legacy.trust_corpus register-file --id sample-001 --path data/external/trust_corpus/sample_001.h264 --source-uri https://example.org/dataset --license CC-BY-4.0 --codec h264 --container raw_h264 --frame-count 300 --resolution 352x288 --source "Example Dataset"
```

The in-video feasibility command is a strict size check, not a proof verifier.
It exits `0` when proof plus framing fits and `3` when it does not; provide a
fresh quality-validated capacity for the exact video and embedding settings.

Upgrade-v2 application-level trust workflows are exposed through
`src.legacy.trust.workflows` for provenance anchoring, fingerprint registry lookup,
watermark receipt, and model/device attestation.
Every workflow output includes a versioned `schema` and `workflow` field, with
validators in `src.legacy.trust.workflow_contracts`.

CLI usage:

```bash
py -3.12 -m src.legacy.trust.workflows provenance --manifest manifest.json --registry-uri registry://example/asset --registry-out provenance_registry.json --output provenance.json
py -3.12 -m src.legacy.trust.workflows fingerprint --frames frames.npy --records registry.json --threshold 0 --output fingerprint.json
py -3.12 -m src.legacy.trust.workflows watermark --frames embedded.npy --key demo-key --frame-shape 64 64 --threshold 0.5 --output watermark.json
py -3.12 -m src.legacy.trust.workflows attestation --signer-key demo-key --video-path video.bin --model-config-path model.json --model-binary-path model.bin --policy-id policy-v1 --timestamp 2026-06-09T00:00:00Z --output attestation.json
py -3.12 -m src.legacy.trust.workflows attestation --signer-scheme ed25519 --signer-key demo-seed --video-path video.bin --model-config-path model.json --model-binary-path model.bin --policy-id policy-v1 --timestamp 2026-06-09T00:00:00Z --output attestation_ed25519.json
```

Section `46` is the product-readiness source of truth. Current state:

- `seed_surface_ready=true`.
- `all_product_ready=false`.
- `product_ready`: C2PA-style local root-anchor registry, local fingerprint-registry lookup receipts, controlled watermark receipt replay, and workflow API/CLI.
- `product_seed`: none.
- `prototype`: software attestation, toy ZK receipt circuits.
- `blocked`: ZKML model binding.

`benchmark.legacy.trust_corpus` currently validates a two-file external CC0 seed
corpus. It is enough for seed-scope evidence, but broad-public-dataset claims
remain blocked until a larger external corpus with source, license, file
metadata, and matching hashes is registered.
(The step-by-step corpus playbook `doc/trust_corpus_onboarding.md` was removed in
the October 2026 cleanup; see the cleanup commits in git history.)

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
4. Verifying the ML-DSA receipt and its in-video commitment (not a ZKP)

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

## Existing Benchmark Outputs (Not Yet Paper-Ready)

These existing results are development artifacts, not a publication-ready
evaluation. The sections have different scopes and validation levels; use the
source JSON/reproduction commands and the corrected SEC5 notes above before
making comparative claims.

For IEEE TIP/TIFS submission:

1. **Quality** (SEC1): locked `akiyo_q22_g1` contract embeds `1232/1232` bits with `53.01 dB` full-video PSNR and `40.30 dB` minimum modified-frame PSNR
2. **Security** (SEC4): chi-square p-value `0.9622`, SPA `0.03762`, RS `0.0` at operating point
3. **ZKP Overhead** (SEC5): the historical artifact is invalid for quantitative claims; the corrected `_new` rerun measured a 129 B Groth16 proof (147 B packed payload), 7042.44 ms proving, and 2208.23 ms verification. Alternative ZKP figures are literature estimates only, and this is not a lattice-proof measurement.
4. **Performance** (SEC6): current committed artifact reports 59.0s pre-processing, 26.1s operational, 85.0s total on `akiyo_q22_g1`
5. **Statistical** (statistical_benchmark.py): 3+ runs with mean/std
6. **Audit** (sec1_audit.py): Quality guard reason logs

---

## Rebuilding Circuit Artifacts

Circuit artifacts are deliberately not committed. Rebuild them from a verified
Powers-of-Tau file and freshly generated secret entropy. The build writes
checksums to `build/artifacts.json`.

```bash
cd legacy/circuits
npm ci
export PTAU_FILE=/absolute/path/to/verified.ptau
export ZKEY_ENTROPY="fresh-secret-entropy-at-least-32-characters"
npm run build
npm run verify-artifacts
```

---

## Documentation

### Project Documentation
- [`docs/LATTICE_ZK_BDLOP_PLAN.md`](docs/LATTICE_ZK_BDLOP_PLAN.md) - Lattice-ZK plan, status and measurements
- [`docs/LATTICE_ZK_BDLOP_SPEC.md`](docs/LATTICE_ZK_BDLOP_SPEC.md) - Lattice-ZK protocol specification
- [`docs/LATTICE_BACKEND_SURVEY.md`](docs/LATTICE_BACKEND_SURVEY.md) - Lattice backend survey
- [`ARTIFACT.md`](ARTIFACT.md) - Reproduction guide for the lattice-ZK evaluation
- [`docs/handoff/`](docs/handoff/README.md) - Vietnamese handoff documentation set
- [`docs/legacy/LATTICE_PQ.md`](docs/legacy/LATTICE_PQ.md) - ML-DSA / ML-KEM attestation path (legacy)
- [`docs/legacy/REALTIME.md`](docs/legacy/REALTIME.md) - Live Annex-B transport contract and native-backend boundary (legacy)
- [`legacy/native/README.md`](legacy/native/README.md) - C17 build, relay, and selected x264 profile (legacy)

The pre-lattice-ZK notes `PAPER_EVIDENCE.md`, `OPERATING_ENVELOPE.md`,
`ARTIFACT_POLICY.md` and `doc/system_video_embedding_walkthrough.tex` were
removed in the October 2026 cleanup (git history).

### Benchmark Documentation
The legacy SEC1-SEC10 benchmark scripts were moved to `benchmark/legacy/` and
most were removed in the October 2026 cleanup (among the SEC scripts only
[`benchmark/legacy/sec4_security.py`](benchmark/legacy/sec4_security.py) and
[`benchmark/legacy/sec5_zkp.py`](benchmark/legacy/sec5_zkp.py) remain). The
current evaluation drivers are `benchmark/latticezk_*.py`;
[`ARTIFACT.md`](ARTIFACT.md) sections 4-5 map each driver to its result file.

### API Documentation
- [`src/legacy/manifest.py`](src/legacy/manifest.py) - Authenticated manifest schema (legacy)
- [`src/legacy/verifier_blind.py`](src/legacy/verifier_blind.py) - Near-blind verification (legacy)
- [`src/legacy/verify_modes.py`](src/legacy/verify_modes.py) - Explicit verifier modes (legacy)
