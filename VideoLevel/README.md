# ZK-SNARK Video Steganography

Hide a Groth16 zero-knowledge proof inside H.264 baseline video by modifying CAVLC coefficients in IDR frames.

**Status:** Research prototype. The current native C++ path embeds a proof-bearing
message inside an H.264 Baseline/CAVLC residual-sign channel and supports blind
key-based extraction without SEI or a sidecar. The supported encoder/profile is
constrained; this is not generic H.264 support.

**Validated Runtime:** `py -3.12`

**Verification:** On 2026-09-24, the full Python phase suite passed 108/108 and
the native fixture, strict FFmpeg decode, blind extraction, and HTTP/WebSocket
tests passed on development hosts. This is functional evidence, not edge
acceptance.

**Realtime status:** Not accepted. The corrected physical-camera H.264 E2E run
measured 7.608 source FPS against the 30-FPS gate. A separate OpenCV Media
Foundation capture-only probe measured 27.868 active FPS with 138.782 ms
read-completion p95 and did not exercise the native stego/HTTP pipeline. No
edge target has been selected or benchmarked.

**Proof boundary:** Groth16 verifies the recovered message/key relation; it does
not prove video integrity, camera origin, or that the proof is bound to a video
commitment.

**Benchmark status:** the legacy SEC1-SEC10 scripts are historical drivers; use the measured `_new` reports and their stated sample limits for the current native CAVLC/HMAC path.

---

## Overview

The current native edge prototype packs the message and compressed Groth16
proof into the payload frame authenticated by the native HMAC channel, then
embeds that frame by changing selected CAVLC residual coefficient signs. The
blind extractor uses the key to recover the frame. Its E2E tests verify the
proof after extraction; native HMAC validation alone is not ZKP verification.

The following legacy public-API workflow additionally describes its optional
chaos transforms and sidecar analysis; do not treat those options as part of
the native camera/HTTP path:

1. Generates a Groth16 proof for the payload.
2. Packs `[4B message_length][message][129B compressed proof]`.
3. Optionally applies chaos transforms:
   - Arnold Cat Map on payload bits
   - Logistic Map on embedding-position order
4. Locates CAVLC-safe candidate positions in IDR frames.
5. Applies length-preserving coefficient/sign modifications.
6. Reconstructs a valid H.264 bitstream.
7. Extracts and verifies the proof from the stego video.

### Legacy research and analysis features (not part of edge acceptance)

- **Versioned Manifest Schema** (v1.0.0): Structured sidecar files with signing hooks
- **Near-Blind Verification**: Reduced cover dependency via sidecar-driven extraction
- **Statistical Benchmarking**: Multi-run error bars for IEEE TIP/TIFS validity (3+ runs)
- **Audit Logging**: SEC1 quality guard tracking with reason logs
- **Modern Detectors**: WS and SPAM steganalysis features
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

The current `_new` suite is documented in [`benchmark/NEW_BENCHMARKS.md`](benchmark/NEW_BENCHMARKS.md). It ran on 2026-09-24 against all nine `data/raw/*.y4m` clips:

- 9/9 full-duration native-resolution H.264 conversions succeeded; frame counts and source cadence are recorded in `benchmark/results/conversion_manifest_new.json`.
- 27/27 media pipeline samples passed (9 clips × 3 resolutions; first 30 frames per case). Full per-frame Y-PSNR and SSIM are in the run CSV; this is not a full-duration embed benchmark.
- Security comparisons execute real library primitives. The native proposal is HMAC-SHA-256 truncated to a 16-byte per-frame tag; the Python HMAC row is a full 32-byte primitive reference, not the native tag's exact timing.
- Groth16 and PLONK proof measurements are actual runs on the same circuit statement. PLONK setup/proving resource costs are substantial; unimplemented proof systems are not assigned estimated timings.

Start with `benchmark/results/performance_new.pdf`, `video_quality_new.pdf`,
`security_new.pdf`, and `zkp_new.pdf`. Machine-readable evidence is in the
adjacent `_new.json` files and `benchmark/results/media_new/<run-id>/`.

Old SEC1–SEC7 JSON datasets, stale run metadata, and the pixel-domain edge
diagnostic have been removed because they belonged to an earlier pipeline;
legacy source scripts remain for reference. Some old PNG charts remain in
`benchmark/results/` because the environment blocked deletion of binary files.
Treat all `sec1_*.png`–`sec7_*.png` files there as historical only; in
particular SEC5 charts include non-comparable/simulated values and must not be
quoted as measurements.

## Project Structure

```text
VideoLevel/
|-- benchmark/
|   |-- diagnostics/              Blind-sync and experimental probes
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
|   |-- sec1_audit.py             Quality guard audit logging
|   `-- safe_benchmark_runner.py  Unified paper/diagnostic runner
|-- circuits/                     Circom circuit + Groth16 keys
|-- data/
|   |-- encoded/                  H.264 benchmark inputs
|   |-- output/                   Stego outputs + sidecars
|   `-- raw/                      Raw source sequences
|-- src/
|   |-- bitstream/                H.264 / CAVLC parsing and patching
|   |-- core/
|   |   |-- pipeline.py           IDR extraction
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

### Run as an authenticated HTTP service

The delivery API is an actual FastAPI/HTTP surface over the existing `embed()`
and strict `verify()` functions. It starts fail-closed: choose a long random
token and set it before starting the service.

```powershell
$env:ZK_STEGO_API_TOKEN = "replace-with-a-long-random-token"
py -3.12 -m uvicorn src.api.app:app --host 127.0.0.1 --port 8080
```

`GET /health` is public. `POST /api/v1/jobs/embed` and
`POST /api/v1/jobs/verify` accept multipart raw `.h264` uploads and return a
job id; `GET /api/v1/jobs/{job_id}` polls safe status; and an embed result is
downloaded at `GET /api/v1/jobs/{job_id}/artifact`. All job routes require
`Authorization: Bearer <token>`. OpenAPI is available locally at `/docs`.

On Windows, the hardware-gated camera E2E can be reproduced by setting
`ZK_STEGO_CAMERA_NAME` to a DirectShow webcam name and running
`py -3.12 src/runtest/test_native_camera_http.py`. It captures into a temporary
directory and deletes the capture after testing; the camera may show its active
indicator during the run.

### Build and test the native core on Linux

The non-Windows CMake path uses OpenSSL Crypto for authenticated frames. The
native library, CLI tools, and CTest suite were verified on Ubuntu 24.04
x86-64 with GCC 13.3 and OpenSSL 3.0.13:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libssl-dev ffmpeg
cmake -S native -B native/edge-build -DCMAKE_BUILD_TYPE=Release
cmake --build native/edge-build -j2
ctest --test-dir native/edge-build --output-on-failure
python3 -u src/runtest/test_native_cli_fixture.py
```

This proves the Linux/OpenSSL build and native fixture tests on x86-64 only;
it is not an ARM build or an edge-device performance result. Confirm the
target OS, architecture, OpenSSL version, camera interface, and encoder profile
before treating this as a deployment recipe. The final fixture E2E checks the
authenticated payload CLI, strict FFmpeg decode, and correct/wrong keys; the
real Groth16 proof is covered by the physical-camera recorder path on the
development host, not by this small Linux fixture check.

On 2026-09-24 the Linux C++ core also passed CTest (1/1, 44.30 s) in an Ubuntu
24.04 x86-64 container (GCC 13.3, OpenSSL 3.0.13, FFmpeg 6.1.1). The Linux-built
CLI embedded a 16-byte payload into the 300-frame fixture; strict FFmpeg decode,
blind extraction with exact payload match, and wrong-key rejection all passed.
The output was 3,551,610 bytes. This is functional Linux x86-64 evidence, not a
camera, ARM, or edge-performance measurement.

For the native CAVLC data plane, build `zkstego_blind_bits` and start the
separate native-backed app instead of treating the legacy Python service as
the edge path:

```powershell
cmake --build native/build --config Release --target zkstego_blind_bits
$env:ZK_STEGO_API_TOKEN = "replace-with-a-long-random-token"
$env:ZK_STEGO_NATIVE_CLI = (Resolve-Path native/build/Release/zkstego_blind_bits.exe).Path
py -3.12 -m uvicorn src.api.native_handlers:create_native_app --factory --host 127.0.0.1 --port 8080 --workers 1 --ws websockets --ws-max-size 1048576 --ws-max-queue 1
```

This app exposes native authenticated `POST /api/v1/jobs/embed` and blind
`POST /api/v1/jobs/extract`; both use the bounded worker/queue and authorized
artifact endpoint. Artifacts are one-time downloads and expire after ten
minutes by default; uploaded source videos are removed after job processing.
Use one Uvicorn worker for this prototype: its bounded queue is process-local.
An OS-backed exclusive lease prevents another service process from sharing the
same work directory.
On restart it marks persisted queued/running jobs failed and removes their
uploaded source and partial output files.
The pinned `websockets` package provides Uvicorn's production WebSocket
protocol backend. The command caps incoming WebSocket messages at 1 MiB and
the server-side receive queue at one message; the application also processes
one chunk at a time and awaits native-stdin drain before reading another.
The native stdin transport uses a 64 KiB high-water mark, and output forwarding
reads at most 64 KiB before awaiting the WebSocket send. The API also rejects
multipart bodies above its aggregate limit and applies a
120-second request-body deadline. The 32-byte key is sent to the child process through stdin,
not argv or a temporary key file. `/api/v1/jobs/verify` deliberately returns
501 here: native payload HMAC validation is not a substitute for ZKP proof
verification. A real DirectShow camera ingest path is exercised separately by
the hardware-gated E2E below; a passing host run is not a claim of performance
on an independent edge target.

To run the physical-camera proof E2E and append measurements to the latest
`benchmark/results/realtime_camera_runs_*.json` artifact, set
`ZK_STEGO_CAMERA_NAME` to an FFmpeg DirectShow device name and run:

```powershell
$env:ZK_STEGO_CAMERA_NAME = "USB2.0 HD UVC WebCam"
uv run --with-requirements requirements.txt python -m benchmark.realtime_camera_recorder --duration 60
```

The recorder appends only after strict decode, frame-count, proof, key-rejection,
and stream-completion gates all pass. It rejects incomplete quality or latency
records, missing CPU/RAM or bounded-flow measurements, inconsistent sample
counts, FPS that disagrees with decoded frames/active duration, absent input or
output byte counts, and NaN/infinite numeric values; Phase 11 exercises these
fail-closed cases. New run records also include the native
CAVLC candidate capacity accumulated over payload-bearing IDR segments and the
exact authenticated-frame bits embedded (payload plus protocol framing/tag);
these are distinct from the Groth16 proof size alone. Use `--results <path>` to
select another JSON artifact. The default duration is five seconds; the
supported range is 1–300 seconds.
Each newly appended record also stores the physical camera name, the DirectShow
input-buffer bound, the pinned libx264 Baseline/CAVLC capture settings,
including `-fps_mode passthrough` so FFmpeg cannot synthesize duplicate frames,
host OS/CPU/RAM and Python version,
FFmpeg version/path, and the native executable's SHA-256. Existing historical
records are intentionally left unchanged and do not gain fabricated metadata.
Native metrics report p50/p95 for payload-bearing patch operations and,
separately, IDR service time for all IDRs (including pass-through frames).
Service timing starts after a complete NAL is read and ends after native output
write/flush; it excludes waiting for input bytes and downstream WebSocket send.
The hardware-gated camera E2E runs Uvicorn and a WebSocket client over loopback
TCP. It pairs Annex-B NAL completions by type/order, records 16 KiB maximum
camera pipe reads, client send-return and receive timestamps, and bounded
server-side stdin-drain / stdout-to-WebSocket-send percentiles. Its
`ffmpeg_stdout_nal_completion_to_websocket_loopback_tcp_nal_completion` number
is host loopback TCP latency—not sensor-exposure-to-display or LAN/TLS latency.
Older run 21 and the isolated 16 KiB experiment used the in-process TestClient
and are labeled separately; see the theory document for decomposed TCP evidence.
After capture, the recorder also scans the full source stream and records raw
candidate signs, the configured-cap whole-stream capacity, and scan duration;
this offline analysis is reported separately from ingest FPS and latency.

#### Carrying and verifying a Groth16 proof through the native channel

The native channel carries authenticated bytes; it does not generate or verify
Groth16 proofs. The client packages the proof with the message before starting
the camera stream, then verifies it after blind extraction. The existing proof
format is `[4-byte big-endian message length][message][129-byte Groth16 proof]`:

```python
import base64
from src.zk_proof import ZKSnarkBridge, pack, proof_to_bytes, unpack

message = b"camera event"
secret_key = load_key_from_secure_storage()  # application-specific secure provisioning
if len(secret_key) != 32:
    raise ValueError("secret key must be exactly 32 bytes")
if len(message) + 4 + 129 > 4096:
    raise ValueError("proof-bearing payload exceeds the native stream limit")

bridge = ZKSnarkBridge("circuits")
proof, _ = bridge.generate_proof_for_payload(message, secret_key)  # before capture
payload = pack(message, proof_to_bytes(proof))
# Send base64(payload) as message_b64 in the authenticated /api/v1/stream embed
# start control; stream raw camera Annex-B chunks, then send {"type": "end"}.

# After extract returns payload_b64:
payload_b64 = receive_payload_b64_from_websocket()  # application WebSocket receive loop
decoded_payload = base64.b64decode(payload_b64, validate=True)
recovered_message, proof_bytes = unpack(decoded_payload)
recovered_proof = bridge.bytes_to_proof(proof_bytes)
if not bridge.verify_proof_for_payload(recovered_proof, recovered_message, secret_key):
    raise ValueError("Groth16 proof verification failed")
```

The 4+129-byte framing leaves at most 3,963 message bytes under the native
4,096-byte stream payload bound. Proof generation is intentionally outside the
camera ingest path; verification occurs after extraction. Wrong-key rejection
at the native transport is HMAC authentication, while the final call above is
the separate Groth16 check. `/api/v1/jobs/verify` remains disabled in the native
service; this client-side sequence is the verified proof path. The circuit
proves the documented message/key relation only, not camera origin or a binding
to the encoded video; see the theory document before making provenance claims.

### Expiring manifest keys

`src.key_policy` issues issuer-signed Ed25519 certificates for manifest public
keys. A conforming verifier rejects a key after `expires_at`. This is enough for
offline policy enforcement, but it cannot defeat a copied private key combined
with a modified clock/verifier. Hard expiration requires an owner-operated
online lease/revocation service, trusted time, or HSM/TEE policy enforcement;
it does not require a commercial third party.

### Benchmark delivery report

See [benchmark/DELIVERY_BENCHMARK.md](benchmark/DELIVERY_BENCHMARK.md) for the
quality, capacity, security, ZKP, time and process-tree resource protocol.
Run `py -3.12 -m benchmark.resource_benchmark --sections 1 2 3 4 5 6` on each
target machine; it preserves the resource result locally without overwriting
the checked benchmark evidence.

### Realtime CAVLC roadmap

The CAVLC-only realtime design, native patcher contract, theory and acceptance
metrics are documented in [doc/realtime_cavlc_theory_and_implementation.md](doc/realtime_cavlc_theory_and_implementation.md).
The evidence audit and remaining edge acceptance gates are tracked in
[doc/completion_plan.md](doc/completion_plan.md).
Before an edge run, copy and fill
[doc/edge_deployment_manifest.template.yaml](doc/edge_deployment_manifest.template.yaml)
with the actual board/toolchain/camera identity and measured acceptance data;
pending/null fields mean the system is not yet qualified for that target.
The tested scheduler is run with `py -3.12 src/runtest/test_phase9_realtime_cavlc.py`.

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
- `cryptography` 50.0.0
- `fastapi` 0.131.0, `uvicorn` 0.41.0, `python-multipart` 0.0.32
- `psutil` 7.2.2 (whole-process resource benchmark)

Observed native toolchain on the current audit machine:

- Python 3.12.10
- Node.js 22.20.0
- `circom` 2.2.0
- `snarkjs` 0.7.6
- `ffmpeg` 8.0.1

Install:

```bash
py -3.12 -m pip install -r requirements.lock
cd circuits
npm ci
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

These verifier modes describe the legacy Python operating-point API. The
native authenticated CAVLC CLI has a separate blind extractor; see the native
fixture and physical-camera E2E instructions above.

### Run tests

The quick suite includes Phase 11 benchmark reproducibility checks (hardware/tool
identity, append-only persistence, and fail-closed metric validation) and Phase
12's real loopback Uvicorn/WebSocket E2E (not only FastAPI's in-process client).

```bash
py -3.12 src/runtest/run_all.py --quick
py -3.12 src/runtest/test_phase4_reconstruct.py
py -3.12 src/runtest/test_phase5_extract_verify.py
py -3.12 src/runtest/test_phase6_security_hardening.py
py -3.12 src/runtest/test_native_http_channel.py
py -3.12 src/runtest/test_future_trust_architecture.py  # experimental interfaces
py -3.12 src/runtest/run_all.py
```

Test exit codes:

- `0`: all selected tests passed.
- `1`: at least one selected test failed.
- `2`: no assertion failed, but at least one required case was skipped, so the
  phase is incomplete and must not be counted as full evidence.

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
- **Legacy Python batch path:** cold-start IDR analysis can dominate (about 1,500 s/video in an older offline benchmark); do not apply that figure to the native streaming CLI.
- **Legacy offline capacity reporting:** raw safe-position counts are not the same as final patchable or quality-validated operating capacity. Native stream records report their own keyed candidate capacity and embedded bits.
- **Python locked operating-point mode:** the older benchmark-grade public API reuses pre-validated operating positions for selected assets; this is separate from native blind CAVLC extraction.
- **Broad Python public API mode:** generic embedding without locked operating positions can under-fill representative assets and should not be used for headline claims; this limitation does not describe the native CLI E2E.
- **Blind-Core research branch:** the experimental Python proxy/analysis branch is not the released data path. Blind extraction is implemented separately in the native authenticated CAVLC CLI and covered by fixture plus camera E2E; neither result establishes generic-profile support or edge readiness.
- **High QP Limits:** QP=32 assets have limited capacity under 40 dB guard.
- **Parser Resync Warnings:** Some streams emit warnings but still decode correctly.

---

## Benchmark Readiness

The `_new` reports are current host measurements, not yet publication-grade or
proof of real-time operation. The media matrix covers the first 30 frames of
each clip/resolution; 13/27 cases fall below the historical 40 dB minimum
modified-frame PSNR floor (worst 32.76 dB). Only Groth16 and PLONK have actual ZKP results; older
SEC5 charts contained non-comparable or simulated values and have been removed.
Use [benchmark/NEW_BENCHMARKS.md](benchmark/NEW_BENCHMARKS.md) for scope and
regeneration commands.

---

## Rebuilding Circuit Artifacts

The repo already includes built artifacts. To rebuild:

```bash
cd circuits
npm ci
npm run compile
```

The proving key and verification key are ceremony artifacts, not package scripts.
Provision them through the trusted-setup workflow before invoking the Python
proof API.

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
