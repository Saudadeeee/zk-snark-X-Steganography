# ZK-SNARK Video Steganography (VideoLevel)

Hide a Groth16 zero-knowledge proof inside H.264 Baseline video by flipping the
signs of selected CAVLC trailing-one coefficients in IDR frames, then recover it
blindly with a key and verify it.

> **Full explanation (Vietnamese):** [`doc/he_thong_hoat_dong.md`](doc/he_thong_hoat_dong.md)
> walks through FFmpeg/libx264, the H.264 bitstream, CAVLC, the embedding channel,
> the keyed schedule, the authenticated frame, Groth16, the service, the demo and
> how to read its debug output. Document index: [`doc/README.md`](doc/README.md).

## Status

| Area | State |
|---|---|
| Maturity | Research prototype. Supported input is constrained (see [Limits](#known-limits)); this is not generic H.264 support |
| Tests | 2026-10-03: `py -3.12 src/runtest/run_all.py` passed **126/126 across 12 phases** (after the single-core consolidation) on a Windows host (fixtures from `prepare_fixtures.py`), native CTest 1/1. Physical-camera E2E (`--hardware`) not included. Functional evidence, not edge acceptance |
| Realtime | **Not accepted.** Corrected physical-camera H.264 E2E: 7.608 source FPS against a 30-FPS gate (measured before the 2026-10-02 native stdin/reader speed-up, not yet re-measured). No edge target benchmarked |
| Proof boundary | Groth16 proves the message/key relation `commitment = SHA256(SHA256(message) ‖ secret)`. It does **not** prove video integrity, camera origin, or bind the proof to the video |
| Benchmarks | Use the `_new` suite ([`benchmark/NEW_BENCHMARKS.md`](benchmark/NEW_BENCHMARKS.md)). SEC1–SEC10 scripts are historical drivers |

## How it works (one screen)

```text
video --FFmpeg/libx264 (Baseline, CAVLC, 1 slice/frame, no B)--> source.h264
message + 32-byte secret --circom/snarkjs Groth16--> proof (129 B compressed)
payload = [len 4B][message][proof 129B]
keys    = HKDF-SHA256(salt "zkstego-cavlc-v2-salt", secret) -> schedule_key, frame_key, whitening_key
frame   = [0x02][len 2B][payload][HMAC-SHA256(frame_key, header||payload)[:16]]
native parser: one candidate per residual block = sign bit of its first trailing one
schedule: sort candidates by HMAC-SHA256(schedule_key, id); frame bit i -> i-th candidate
whiten: embedded bit i = frame bit i XOR keystream bit i, keystream = HMAC-SHA256(whitening_key, block counter)
embed: set those sign bits (bit length, TotalCoeff and nC unchanged -> stream stays valid)
receiver: same parser + key -> same schedule -> read + un-whiten -> check version/HMAC -> unpack -> snarkjs verify
```

There is one media core: native C++ ([`native/`](native/)). Python orchestrates
proof generation, packaging, the HTTP/WebSocket service and the demo. The earlier
pure-Python H.264 pipeline was removed on 2026-10-03 (recoverable from git history).

Circuit `circuits/payload_verify.circom` (`PayloadVerify`): 63,321 constraints,
513 public inputs (`payload_hash[256]`, `commitment[256]`, `payload_length`),
private `secret[256]`; every hash, commitment and secret signal is constrained to 0/1. Proving/verification keys are a local educational setup
(`circuits/build/DEMO_SETUP_ONLY.txt`), not a production trusted ceremony.

## Repository layout

```text
VideoLevel/
|-- native/                     C++20 data plane
|   |-- include/zkstego/        cavlc_stream.hpp (parser, candidates, schedule, frames, stream codec)
|   |-- src/cavlc_stream.cpp
|   |-- tools/                  zkstego_blind_bits (embed/extract CLI), zkstego_inspect (inspection), cli_io.hpp
|   `-- tests/                  CTest suite
|-- circuits/                   Circom circuits, snarkjs (npm), build/ (git-ignored keys and artifacts)
|-- src/
|   |-- zk_proof.py             Groth16 bridge, 129-byte proof compression, pack/unpack
|   |-- native_blind_contract.py  Python reference of the native schedule/frame ABI
|   |-- api/                    FastAPI job core (app.py) + native embed/extract/verify + WebSocket (native_handlers.py)
|   |-- realtime_cavlc.py       Bounded realtime segment scheduler
|   |-- h264_tables.py          H.264 CAVLC VLC tables (used by the demo's explanation code)
|   |-- manifest.py, key_policy.py  Signed manifest schema and expiring manifest-key certificates
|   |-- trust/                  Experimental provenance / C2PA-style anchor / fingerprint / attestation
|   `-- runtest/                Test phases, run_all.py, prepare_fixtures.py
|-- demo/                       terminal_demo.py (the single demo) + deep_trace.py, h264_explain.py
|-- benchmark/                  *_new suite (media/crypto/ZKP), realtime camera recorder, results/
|-- data/raw/foreman_cif.y4m    Tracked raw source for fixtures and the demo
|-- doc/                        System documentation (Markdown + LaTeX/PDF)
|-- output/                     Presentation and PDF deliverables
|-- future_plan.md              Next-version design (Vietnamese)
`-- requirements.txt
```

## Requirements

- Python 3.12 (`py -3.12`), packages from `requirements.txt`
- CMake and a C++20 compiler (MSVC on Windows; GCC/Clang + OpenSSL `libssl-dev` elsewhere)
- Node.js 22.x; `circom` 2.2.x; snarkjs 0.7.x via `circuits/package-lock.json`
- FFmpeg with libx264 and ffprobe on `PATH` (validated with 8.0.1)

## Setup

```powershell
py -3.12 -m pip install -r requirements.txt
cd circuits; npm ci; cd ..
cmake -S native -B native/build -DBUILD_TESTING=ON
cmake --build native/build --config Release
py -3.12 demo/terminal_demo.py --setup         # compiles the circuit and creates a LOCAL demo Groth16 setup if keys are missing
py -3.12 src/runtest/prepare_fixtures.py       # regenerates git-ignored data/encoded/*.h264 from data/raw
```

Linux (verified on Ubuntu 24.04 x86-64, GCC 13.3, OpenSSL 3.0.13; not an ARM or edge result):

```bash
sudo apt-get install -y build-essential cmake libssl-dev ffmpeg
cmake -S native -B native/edge-build -DCMAKE_BUILD_TYPE=Release
cmake --build native/edge-build -j2
ctest --test-dir native/edge-build --output-on-failure
```

CMake options: `ZKSTEGO_WARNINGS` (default ON), `ZKSTEGO_SANITIZE` (ASan/UBSan, GCC/Clang only, default OFF).

## Demo

```powershell
py -3.12 demo/terminal_demo.py --auto --message "Xin chao"     # full walkthrough with deep trace
py -3.12 demo/terminal_demo.py --auto --brief --no-service     # skip deep trace and HTTP/WebSocket steps
py -3.12 demo/terminal_demo.py --auto --frames 48 --gop 12     # include P frames
```

The deep trace shows FFmpeg/libx264 internals from their own logs, NAL/EBSP/RBSP
cutting, every SPS/PPS/slice-header field via FFmpeg's `trace_headers`, and the
full life of one embedded 4×4 block (header bits → CAVLC elements → coefficients →
dequantization → inverse transform → intra prediction → pixels → deblocking),
plus where the embedded bit sits in the file and which payload field it carries.
Every recomputed value is checked against FFmpeg or the native parser
(`[PASS]`/`[FAIL]`). It uses the same segment protocol as the service, shows which
IDR carries which frame-bit range, runs the rejection cases (changed message,
invalid/missing proof, wrong key, one flipped carrier bit) and then drives the real
HTTP jobs (embed, extract, verify) and the WebSocket stream. Without
`--max-bits-per-idr` the per-IDR cap starts at 64 and is raised to the smallest value
that fits the payload; an explicit cap is never changed. Artifacts go to
`demo/runs/` (git-ignored). Details: [`demo/README.md`](demo/README.md).

## Native CLI

All commands read the 32-byte key as one 64-hex-character line (never argv) and exit 2 on any error.

```powershell
# embed: stdin = key hex line, payload hex line
zkstego_blind_bits embed-stream-auth-stdin in.h264 out.h264 64
# blind extract: stdin = key hex line; stdout = authenticated payload hex
zkstego_blind_bits extract-stream-auth out.h264 - 4096 64
```

| Command | Purpose |
|---|---|
| `embed-stream-auth-stdin`, `extract-stream-auth` | Files: authenticated frame spread over IDR segments (SPS+PPS+IDR), `max-bits-per-IDR` cap |
| `measure-live-capacity-stdin` | Candidate capacity of an Annex-B stream on stdin (JSON) |
| `embed-live-auth-stdin`, `extract-live-auth-stdin` | Same segment protocol over stdin/stdout (used by the WebSocket service) |

There is one protocol (segments) for files, HTTP jobs and live streams.

`zkstego_inspect input.h264` dumps NALs, slices and candidates as JSON;
`--summary` prints a readable overview; `--macroblock NAL MB` gives every MB
header of the slice and every CAVLC element of one MB; `--segments MAX_BITS`
lists the per-segment candidates so a caller can reproduce the exact embedding
schedule (`src.native_blind_contract.segment_schedule`).

### Carrying and verifying a proof

The native channel authenticates bytes; Groth16 generation and verification happen in Python:

```python
from src.zk_proof import ZKSnarkBridge, pack, proof_to_bytes, unpack

bridge = ZKSnarkBridge("circuits")
proof, _ = bridge.generate_proof_for_payload(message, secret_key)   # secret_key: 32 bytes
payload = pack(message, proof_to_bytes(proof))                     # <= 4096 bytes -> message <= 3963 bytes
# ... embed payload, transmit, blind-extract payload ...
recovered_message, proof_bytes = unpack(payload)
if not bridge.verify_proof_for_payload(bridge.bytes_to_proof(proof_bytes), recovered_message, secret_key):
    raise ValueError("Groth16 proof verification failed")
```

`bytes_to_proof` rejects malformed points (`ValueError`); verification accepts
only when snarkjs exits 0 and prints `OK!`.

## HTTP / WebSocket service

```powershell
$env:ZK_STEGO_API_TOKEN = py -3.12 -c "import secrets; print(secrets.token_urlsafe(32))"   # >= 32 characters required
$env:ZK_STEGO_NATIVE_CLI = (Resolve-Path native/build/Release/zkstego_blind_bits.exe).Path
py -3.12 -m uvicorn src.api.native_handlers:create_native_app --factory --host 127.0.0.1 --port 8080 `
    --workers 1 --ws websockets --ws-max-size 1048576 --ws-max-queue 1
```

| Route | Notes |
|---|---|
| `GET /health` | Public |
| `POST /api/v1/jobs/embed`, `POST /api/v1/jobs/extract` | Multipart `.h264` upload → job id; bounded worker/queue |
| `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/artifact` | Status; one-time artifact download, expires after 10 minutes |
| `WS /api/v1/stream` | JSON start frame, then binary Annex-B chunks; `{"type": "end"}` to finish |
| `POST /api/v1/jobs/verify` | Blind extract, then mandatory Groth16 verification: `succeeded` with the message only when the proof verifies; otherwise `rejected` with a reason (`payload_not_authenticated`, `malformed_proof_payload`, `proof_invalid`) |

Job status values: `queued`, `running`, `succeeded`, `rejected` (a verify job whose
Groth16 proof did not verify; clients must not treat it as success), `failed`.

Protections: the Bearer token (at least 32 characters) is required and checked
before any body byte is read, also behind `--root-path`; 10 failed authentications
from one client IP within 60 s give `429` with `Retry-After` on HTTP and WebSocket;
at most 4 concurrent uploads; size limits and an upload deadline
(`ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS`, default 120);
unauthenticated WebSocket handshakes are refused before accept (HTTP 403);
idle streams close after `ZK_STEGO_STREAM_IDLE_TIMEOUT_SECONDS` (15); finished
jobs are purged after `ZK_STEGO_API_JOB_RETENTION_SECONDS` (86400); OpenAPI
`/docs` only with `ZK_STEGO_API_DOCS=1`. Other settings: `ZK_STEGO_NATIVE_CLI`
(path to `zkstego_blind_bits`), `ZK_STEGO_MAX_BITS_PER_IDR` (default 64; embed and
extract must agree), `ZK_STEGO_CIRCUITS_DIR` (verification keys, default `circuits`). Keys reach the native child through
stdin; the child runs without a shell, with timeouts and drained stderr. Use one
Uvicorn worker: the queue is process-local and a work-directory lease prevents
sharing.

## Tests

```powershell
py -3.12 src/runtest/run_all.py              # all phases
py -3.12 src/runtest/run_all.py --quick      # fast subset
py -3.12 src/runtest/run_all.py --hardware   # + physical camera E2E (needs ZK_STEGO_CAMERA_NAME)
ctest --test-dir native/build -C Release --output-on-failure
```

On Windows set `PYTHONIOENCODING=utf-8`. Exit codes: `0` all passed, `1` failure,
`2` a required case was skipped (incomplete evidence). Phases:

| Phase | Covers |
|---|---|
| 1 | `test_zk_proof.py`: Groth16 proof format, compression, fail-closed verification |
| 2 | `test_native_blind_contract.py`: C++ and Python agree on HKDF, schedule, frame, whitening, segment schedule |
| 3 | `test_native_cli_fixture.py`: CLI embed/extract on the 300-frame fixture, strict decode, wrong key |
| 4 | `test_h264_tables.py`: CAVLC VLC tables (prefix-free, Kraft, spec values) |
| 5 | `test_service_api.py`: job core, auth-before-body, throttling, retention, verify job, key expiry |
| 6 | `test_native_http_channel.py`: real Uvicorn HTTP jobs and WebSocket stream |
| 7 | `test_manifest_security.py`: manifest signing and positions/stego binding |
| 8 | `test_realtime_scheduler.py`: bounded realtime scheduler |
| 9 | `test_benchmark_recorder.py`: camera recorder fail-closed checks |
| 10 | `test_trust_interfaces.py`: experimental provenance/C2PA/attestation interfaces |
| 11 | `test_demo_h264_explain.py`: demo math matches the native parser and FFmpeg pixels |
| 12 | `test_demo_smoke.py`: the whole demo runs with no `[FAIL]` |
| H1 | `test_native_camera_http.py` (`--hardware`): physical camera E2E |

## Benchmarks

- **Current:** `py -3.12 -m benchmark.run_new_suite` (media conversion/quality,
  crypto, ZKP). Scope, sample limits and regeneration commands:
  [`benchmark/NEW_BENCHMARKS.md`](benchmark/NEW_BENCHMARKS.md); delivery protocol:
  [`benchmark/DELIVERY_BENCHMARK.md`](benchmark/DELIVERY_BENCHMARK.md). Reports:
  `benchmark/results/*_new.pdf` and `*_new.json`, per-run data under
  `benchmark/results/media_new/<run-id>/`. The 2026-09-24 run used nine raw
  clips (only `foreman_cif.y4m` is tracked); media rows cover the first 30 frames
  per case, and in run `20260924T150707Z_2be60c` 13/27 cases fall below the historical
  40 dB modified-frame PSNR floor (worst 32.76 dB).
- **Physical camera:** set `ZK_STEGO_CAMERA_NAME` to a DirectShow device and run
  `py -3.12 -m benchmark.realtime_camera_recorder --duration 60`; records are
  appended to `benchmark/results/realtime_camera_runs_*.json` only after strict
  decode, frame-count, proof, key-rejection and stream-completion gates pass.
  Measurement details: [`doc/realtime_cavlc_theory_and_implementation.md`](doc/realtime_cavlc_theory_and_implementation.md).
- The `_new` suite samples CPU/RSS of the native child per row, so a separate
  resource runner is not needed. The SEC1–SEC10 scripts of the removed Python
  pipeline are in git history only; their results are not current evidence.
- Recorded `_new`, camera and media results predate protocol v2 and the
  bit-constrained circuit (2026-10-03); re-run before citing them for this version.

## Known limits

- Input profile: Baseline, CAVLC, progressive, 4:2:0, one slice per frame starting
  at MB 0, no I_PCM, one SPS/PPS id. Only IDR frames carry data.
- The native channel derives separate schedule, tag and whitening keys with HKDF
  (protocol v2), but the circuit uses the raw secret, and the verifier must hold it
  to recompute the commitment.
- Frames and proofs carry no video/session binding and can be replayed into another
  video under the same key (design work: `future_plan.md`).
- Protocol v2 (2026-10-03) cannot read stego files made with v1, and proofs made with
  the previous circuit keys do not verify against the current keys.
- Realtime not accepted; no edge-device measurements.

Plans for these: [`future_plan.md`](future_plan.md); evidence audit and open gates:
[`doc/completion_plan.md`](doc/completion_plan.md).
