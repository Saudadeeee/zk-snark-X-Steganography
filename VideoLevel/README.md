# ZK-SNARK Video Steganography

Hide a Groth16 zero-knowledge proof inside H.264 baseline video by modifying CAVLC coefficients in IDR frames.

**Status:** Research prototype with validated all-intra benchmark path  
**Validated Runtime:** `py -3.12`  
**Tests:** Phase 2/3 currently re-validated on the maintained asset set; full legacy suite requires further stabilization

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

Public inputs:

- `payload_hash[256]`
- `commitment[256]`
- `payload_length`

Private input:

- `secret[256]`

---

## Current Benchmark Snapshot

All results below were regenerated on `2026-05-05` using the real proof pipeline and `py -3.12`.

### SEC1: Quality at the true 1232-bit operating point

All listed operating points now satisfy all of the following simultaneously:

- full real-proof embedding: `1232/1232` bits
- end-to-end proof verification after extraction
- `min_modified_frame_psnr > 40 dB`

Representative SEC1 results:

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

### SEC2: Capacity

Representative SEC2 capacity results at the same operating point:

| Sequence | Raw T1 capacity | Operating positions | Utilization of raw capacity | PSNR at 1232 bits |
|---|---:|---:|---:|---:|
| Foreman QP22 G1 | 286,745 bits | 1,232 bits | 0.430% | 55.15 dB |
| Coastguard QP22 G1 | 427,883 bits | 1,232 bits | 0.288% | 51.23 dB |
| Football QP22 G1 | 372,266 bits | 1,232 bits | 0.331% | 52.24 dB |
| Deadline QP22 G1 | 1,735,622 bits | 1,232 bits | 0.071% | 58.55 dB |
| Coastguard QP22 G1 (3000f) | 4,278,830 bits | 1,232 bits | 0.029% | 60.92 dB |

### SEC4: Steganalysis operating point

- Foreman QP22 G1 operating point: `chi-square p = 0.9622`
- SPA at operating point: `0.03762`
- RS delta at operating point: `0.0`

### SEC7: Fixed-payload operating-point summary

Under the current fixed `1232`-bit operating payload and the strict `frame-min PSNR > 40 dB` guard:

- `11/11` tested SEC1 operating points pass the strict criterion
- Every passing point also verifies the extracted Groth16 proof successfully

---

## Project Structure

```text
VideoLevel/
├─ benchmark/                Benchmark scripts and result artifacts
├─ circuits/                 Circom circuit + Groth16 keys
├─ data/
│  ├─ encoded/               H.264 benchmark inputs
│  ├─ output/                Stego outputs + positions.json
│  └─ raw/                   Raw source sequences
├─ src/
│  ├─ bitstream/             H.264 / CAVLC parsing and patching
│  ├─ core/                  Pipeline, chaos, safety filter, embed logic
│  ├─ runtest/               5-phase test suite
│  ├─ embedder.py            Public embed API
│  ├─ verifier.py            Public verify API
│  └─ zk_proof.py            Proof packing + snarkjs bridge
├─ instruction.md           Benchmark operating rules
├─ plan.md                  Paper-readiness status
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
```

### Verify

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

### Run tests

```bash
py -3.12 src/runtest/run_all.py
```

Expected summary:

```text
[+] Phase 1   ZK Proof             7/7 passed
[+] Phase 2   H264 Parser          8/8 passed
[+] Phase 3   Safety + Embed       8/8 passed
[+] Phase 4   Reconstruct          5/5 passed
[+] Phase 5   Extract + Verify     4/4 passed
TOTAL: 32/32 passed
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

### Bit-exact reconstruction

`BitstreamPatcher` re-encodes only the modified block and applies the patch only if the encoded bit length matches the original NAL slice region exactly.

### Extraction

`extract_bits_direct()` uses the original verified offsets from the cover stream. Because embedding is length-preserving, those offsets remain valid in the stego stream.

---

## Benchmark Workflow

The authoritative workflow is in [instruction.md](instruction.md).

Typical commands:

```bash
$env:SEC1_USE_REAL_PROOF_PIPELINE='1'
py -3.12 benchmark/sec1_quality.py --force
py -3.12 benchmark/sec2_capacity.py --force
py -3.12 benchmark/sec3_methods.py --force
py -3.12 benchmark/sec4_security.py --force
py -3.12 benchmark/sec7_tradeoff.py
```

Developer iteration commands:

```bash
$env:BENCHMARK_TRUSTED_IDR_PICKLE_CACHE='1'
py -3.12 benchmark/sec1_quality.py --fast --sequences foreman_q22_g1
py -3.12 benchmark/sec2_capacity.py --fast --sequences foreman_q22_g1
py -3.12 benchmark/sec3_methods.py --fast
py -3.12 benchmark/sec4_security.py --fast --force
py -3.12 benchmark/sec6_performance.py --fast --sequences foreman_q22_g1
py -3.12 src/runtest/run_all.py --quick
py -3.12 benchmark/safe_benchmark_runner.py --fast --sections 1 2 3 4 6
```

Notes:

- `--fast` is intended for developer iteration, not headline paper numbers.
- Benchmark luma decode is now cached under `.cache/benchmark_frames/`.
- Cover-video analysis is now reused across `sec1/sec2/sec3/sec4` via `.cache/video_analysis/`.
- Repeated runs on the same sequence are much faster once the sec1/analysis caches are warm.

Artifacts are written to:

- `benchmark/results/*.json`
- `benchmark/results/*.png`
- `data/output/sec1_stego_*.h264`
- `data/output/sec1_stego_*.h264.positions.json`

---

## Known Limits

- The default `python` on this machine may not have `numpy`; the validated runtime is `py -3.12`.
- Current strongest operating mode is `GOP=1` / all-intra. GOP>1 support remains exploratory and degrades sharply on the current GOP8 benchmark assets.
- Benchmark cold-start on a new video is still dominated by IDR extraction; frame decode caching and sec1 fast mode only reduce the repeated-run cost.
- `foreman_q32_g1` currently does not sustain the full `1232`-bit operating payload under the 40 dB per-frame guard because the available asset is only 50 frames.
- `benchmark/sec7_tradeoff.py` currently derives QP recommendations from the tested all-intra assets only; a full GOP sweep is still future work if the paper must claim bitrate-optimal operating points beyond `GOP=1`.
- Some benchmark runs emit `TraceableParser resync failed ...` warnings on difficult streams. Current accepted artifacts still decode correctly and pass downstream quality/verification checks.

---

## Rebuilding Circuit Artifacts

The repo already includes:

- `circuits/build/proving_key.zkey`
- `circuits/build/verification_key.json`
- `circuits/build/payload_verify.r1cs`
- `circuits/build/payload_verify_js/`

If you need to rebuild them:

```bash
cd circuits
circom payload_verify.circom --r1cs --wasm --sym -o build/
npx snarkjs groth16 setup build/payload_verify.r1cs build/pot17_final.ptau build/circuit_0000.zkey
npx snarkjs zkey contribute build/circuit_0000.zkey build/proving_key.zkey --name="contribution" -v
npx snarkjs zkey export verificationkey build/proving_key.zkey build/verification_key.json
```

---

## Paper Status

See [plan.md](plan.md) for the current paper-readiness checklist.
