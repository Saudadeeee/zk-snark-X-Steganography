# ZK-SNARK Video Steganography

Hide a Groth16 zero-knowledge proof inside H.264 baseline video by modifying CAVLC coefficients in IDR frames.

**Status:** Paper-ready benchmark set on `main`  
**Validated Runtime:** `py -3.12`  
**Tests:** `32/32 passed`

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

All results below were regenerated on `2026-04-30` using the real proof pipeline and `py -3.12`.

### SEC1: Quality at the true 1232-bit operating point

| Sequence | Full-video PSNR | Avg SSIM | Embedded bits |
|---|---:|---:|---:|
| Foreman QP18 G1 | 49.45 dB | 0.9994 | 1232/1232 |
| Foreman QP22 G1 | 54.79 dB | 0.9998 | 1232/1232 |
| Foreman QP28 G1 | 47.61 dB | 0.9990 | 1232/1232 |
| Coastguard QP18 G1 | 52.92 dB | 0.9998 | 1232/1232 |
| Coastguard QP22 G1 | 52.46 dB | 0.9998 | 1232/1232 |
| Coastguard QP28 G1 | 49.00 dB | 0.9996 | 1232/1232 |
| Coastguard QP32 G1 | 48.48 dB | 0.9995 | 1232/1232 |
| Deadline QP22 G1 | 59.03 dB | 1.0000 | 1232/1232 |

Note:

- `foreman_q32_g1` is currently **not** paper-valid at the same operating point. On the available 50-frame asset, the pipeline falls below the 40 dB per-frame guard after bad-IDR removal and cannot keep all `1232` bits.

### SEC2: Capacity

| Sequence | Raw T1 capacity | Validated pool | Utilization of raw capacity |
|---|---:|---:|---:|
| Foreman QP22 G1 | 286,745 bits | 1,332 bits | 0.430% |
| Coastguard QP22 G1 | 427,883 bits | 1,316 bits | 0.288% |
| Deadline QP22 G1 | 1,735,622 bits | 1,321 bits | 0.071% |

### SEC4: Steganalysis operating point

- Foreman QP22 G1 operating point: `chi-square p = 0.962`
- RS delta at operating point: `0.0`

### SEC7: Fixed-payload QP recommendations

Under the current fixed `1232`-bit operating payload and the strict `frame-min PSNR >= 40 dB` guard:

| Sequence | Best tested QP |
|---|---:|
| Foreman | 28 |
| Coastguard | 32 |
| Deadline | 22 |

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

Artifacts are written to:

- `benchmark/results/*.json`
- `benchmark/results/*.png`
- `data/output/sec1_stego_*.h264`
- `data/output/sec1_stego_*.h264.positions.json`

---

## Known Limits

- The default `python` on this machine may not have `numpy`; the validated runtime is `py -3.12`.
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
