# Realtime CAVLC Theory and Implementation

## Purpose and current status

This document specifies the constrained native data plane: change selected
trailing-one signs in H.264 Baseline/CAVLC residual syntax inside Annex-B IDR
segments. Payload bytes must not be carried by SEI, NAL headers, container
metadata, or a spatial-pixel fallback. Unsupported syntax is rejected; this
is not a generic H.264 editor.

Current functional implementation and evidence:

- `native/` traverses the locked single-slice progressive 4:2:0 I/IDR profile,
  selects keyed sign positions, rewrites RBSP/EBSP without changing sign-field
  bit lengths, and supports blind authenticated extraction.
- Fixture E2E has passed on Windows and Linux x86-64: correct-key recovery,
  wrong-key rejection, and strict `ffmpeg -v error -xerror` decode. The Linux
  CTest and fixture result are recorded below.
- `src/api/native_handlers.py` exposes bounded HTTP jobs and an authenticated
  WebSocket stream that forwards camera bytes incrementally to the native CLI.
  Physical-camera run 19 is a 60-second development-host soak: it strictly
  decoded 1,801 frames, verified the recovered Groth16 proof, and rejected a
  wrong key. Runs 18 and 19 include camera, toolchain, host, and native-binary
  identity metadata.
- `src/realtime_cavlc.py` remains a separately tested scheduling controller;
  it is not the scheduler used by the camera WebSocket path.

These results establish functional fixture and development-host camera paths,
not edge readiness. The measured camera is USB UVC without an H.264 hardware
output; FFmpeg software-encodes its YUYV/MJPEG capture to the pinned Baseline,
CAVLC, all-intra profile. No target-edge camera/SoC throughput or sustained
thermal benchmark has been recorded. See the acceptance table and measured
limits below; do not extrapolate the host numbers to an edge deployment.

## CAVLC embedding theory

For an H.264 Baseline residual 4x4 block, let its quantized transform
coefficients in zigzag order be `c[0], ..., c[15]`. A CAVLC-safe sign channel
encodes one bit at coefficient `c[k]` as:

```text
bit 0: c'[k] =  abs(c[k])
bit 1: c'[k] = -abs(c[k])
```

The candidate must satisfy all of the following:

1. It is an AC coefficient, never DC.
2. Its magnitude is nonzero and its support does not change.
3. In the blind sign channel, it is a genuine CAVLC trailing-one sign flag;
   the flag offset is immediately after `coeff_token` and changing it must not
   alter any other CAVLC syntax bit. (The conventional LSB channel instead
   excludes trailing ones.)
4. Its re-encoded block has the same bit length as the source block.
5. The replacement must preserve a decodable slice and pass visual-quality
   policy.

Sign changes alter reconstructed pixels through the inverse transform while
keeping payload inside compressed video content. They are not metadata.

### ChromaAC context and bounds

For 4:2:0 ChromaAC, the DC transform coefficient is coded separately and an
AC block has `maxNumCoeff = 15`, not 16. Consequently `total_zeros` is absent
when `TotalCoeff == 15`; consuming the luma `TotalCoeff == 15` VLC at that
point corrupts the next block boundary.

`nC` for a ChromaAC `coeff_token` is derived from neighbouring **AC** blocks
of the same component (Cb never borrows Cr counts, and neither uses a
ChromaDC count). If both neighbouring macroblocks are available,
`nC = (nA + nB + 1) >> 1`; otherwise `nC = nA + nB`, with an unavailable,
skip, or uncoded neighbour contributing zero. This rule is a parsing invariant
for native traversal, not an optional estimator. The native full-slice reader
retains this state per component across macroblock boundaries for the locked
progressive, one-slice camera profile; FMO, MBAFF, CABAC, and nonzero
`first_mb_in_slice` are rejected rather than guessed.

## Realtime segment protocol

```text
camera encoder (Baseline, CAVLC, short all-intra GOP)
  -> Annex-B IDR segmenter
  -> bounded queue
  -> native CAVLC parser and safe-position selector
  -> proof epoch cache
  -> native sign patcher and RBSP emulation-prevention rewrite
  -> H.264 output
```

`RealtimeCAVLCScheduler` follows three operational rules:

- Capture must never wait for proof generation or a slow patch.
- At overload, discard the oldest unprocessed segment; do not silently grow
  latency.
- A proof is generated once for an epoch and reused by its segments.

The scheduler now enforces both segment-count and byte bounds (defaults: two
queued segments, 16 MiB per segment, 32 MiB queued total), evicts oldest queued
segments until a new segment fits, and rejects a single segment larger than
the configured byte limit. Non-finite FPS/latency budgets are rejected. Proof
cache and latency history are bounded (four epochs and 4,096 samples by
default), and concurrent consumers serialize proof creation while queue
submission remains independent of the proof callback. Epochs must be
non-decreasing; this lets bounded LRU eviction remain safe for a forward-only
stream and prevents an old epoch from silently regenerating its proof. These
are controller unit-test guarantees only: this scheduler is not yet wired to
the physical camera or native HTTP service, so they do not establish live
streaming.

The output is acceptable only when queue drops are zero and p95 CAVLC patch
latency is at most the frame interval (`1 / FPS`) or an explicitly stricter
budget.

## Native patcher contract

The native library now exposes stateful authenticated segment processing:

```text
AuthenticatedCavlcStreamEncoder.process_segment(one_idr_segment)
  -> patched_segment, candidate_capacity, bits_embedded, session_complete
AuthenticatedCavlcStreamDecoder.consume_segment(one_idr_segment)
  -> blind extraction state; verify HMAC when the framed payload is complete
```

Each call scopes keyed candidate ranking to exactly one IDR segment, so it no
longer needs future frames to choose positions. The authenticated frame's bits
are carried forward across segments, bounded by a configured maximum number
of bits per segment; the final segment is zero-padded to the same observable
capacity rule. The decoder independently derives that capacity, reads the
length-prefixed frame, and rejects an invalid key/tag. It accepts only one
supported IDR slice per segment and no P-slice. This native stateful API has
fixture unit coverage and is now reached by the native HTTP job adapter through
the `embed-stream-auth-stdin` / `extract-stream-auth` CLI operations. The file-job
adapter still accepts a completed `.h264` upload; live ingest is available
separately through the WebSocket relay described below.
`ZK_STEGO_MAX_BITS_PER_IDR` configures the shared encoder and
blind decoder cap (default 64, must be positive). The CLI walks Annex-B NALs,
updates its SPS/PPS context, and processes each supported IDR slice independently;
non-IDR NALs are passed through unchanged. This currently requires one supported
IDR slice NAL per processed segment; the wrapper does not group type-5 slices by
picture or validate multi-slice picture semantics. Therefore deployment is still
scoped to the locked single-slice Baseline/CAVLC encoder configuration; other
camera syntax is not yet established as supported.
The decoder is terminal after any malformed segment, header, or
tag; it wipes partial recovered bits and refuses later chunks. Segment order
is significant: dropping/reordering encoded segments causes authentication
failure. This protocol currently has no sequence number, nonce, or replay
protection, so a stream-session wrapper must supply and authenticate freshness
before it is suitable for evidence use.

Live embed metrics report both `bits_embedded` and
`candidate_capacity_bits`. The former is the exact authenticated native frame
size in bits (version + 16-bit payload length + payload + 16-byte HMAC tag);
the latter is the sum of candidate capacity from each payload-bearing IDR
segment processed through completion, after the configured per-IDR cap. It is
not a maximum capacity for the entire camera mode or a theoretical bound.
Comparing these fields prevents proof-byte length from being mistaken for the
actual CAVLC transport cost. Camera run records produced by the recorder require
capacity to be at least the embedded frame size.

The benchmark separately runs `measure-live-capacity-stdin <max-bits-per-IDR>`
over the entire captured source stream. This incremental native scan reports
all IDR segments, all keyed-schedule-eligible trailing-one signs, and the
sum of `min(configured per-IDR cap, eligible signs)` over the whole stream.
That whole-stream bound must not be confused with capacity consumed before one
particular payload finishes embedding; its scan time is reported separately
and is not part of the live-ingest FPS or latency figures.

The native stream response also reports `idr_service_p50_ms` and
`idr_service_p95_ms` over completed IDR NALs, including passthrough IDRs after
the payload completes. Timing begins once `AnnexBNalStreamReader` has returned
a complete NAL and ends after native stdout write/flush; it excludes waiting
for incoming bytes and downstream WebSocket send. `segment_process_p50_ms` /
`segment_process_p95_ms` remain a separate measurement over payload-bearing
IDRs only. If those modified segments are under five percent of a clip, the
all-IDR p95 is expected to describe mostly passthrough service time; use the
patched-segment metric to see the heavier embedding tail. Both are host-local
service times, not sensor-to-client end-to-end latency.

The native CLI additionally exposes `embed-live-auth-stdin` and
`extract-live-auth-stdin`. They consume a bounded text control preamble (key,
and for embedding the payload), then treat the remaining stdin bytes as raw
Annex-B and forward embedded video to stdout NAL-by-NAL. The reader handles
start codes split across reads, caps one NAL at 16 MiB, and writes/flushes each
NAL so a pipe's finite OS buffer supplies backpressure. It necessarily waits
for the following start code to know a NAL is complete. If the input ends
before the payload frame fits, embedding exits unsuccessfully; consumers must
treat nonzero exit or stream closure before completion as failure. This CLI
primitive is not itself an HTTP relay; the authenticated WebSocket adapter
described below connects it to a duplex channel. The API job handler still
uses completed uploads.

Remaining native/controller work includes:

1. Parse SPS/PPS once per stream and parse each IDR slice incrementally.
2. Decode enough CAVLC syntax to locate selected luma residual levels and
   retain exact start/end bit offsets.
3. Derive deterministic, key-ordered safe candidates; one modification per
   block by default.
4. Re-encode only length-invariant blocks, then rewrite the selected RBSP,
   regenerate emulation-prevention bytes, and preserve unrelated Annex-B NAL
   units byte-for-byte.
5. Return an unchanged segment when its validated capacity is insufficient;
   report that condition as a controlled drop/failure, never partial silent
   embedding. (Current behavior does this for a zero-candidate segment; the
   session advances only by the number of bits actually carried.)
6. Expose per-segment parse, patch, proof-wait and total-latency metrics.

## Performance plan

The batch benchmark is not a realtime benchmark. A target device must measure:

| Metric | Acceptance rule |
| --- | --- |
| CAVLC parse plus patch p50/p95 | p95 <= frame interval |
| End-to-end camera latency | within deployment budget |
| Queue drops | zero at sustained target FPS |
| CPU and RSS | recorded per target device |
| Decodability | FFmpeg or hardware decoder accepts every output segment |
| Quality | PSNR and SSIM against source capture |
| Payload integrity | extracted proof verifies after every run |

Run the scheduler contract test with:

```powershell
py -3.12 src/runtest/test_phase9_realtime_cavlc.py
```

Phase 9 remains a scheduler contract test, not a performance acceptance test.
The native implementation now has a cross-platform fixture E2E and a physical
camera-to-WebSocket E2E on the development host (see the results below). Those
runs establish functional behavior and host measurements only; every metric in
the table still needs to be collected on the intended edge target before a
realtime/edge claim can be made.

### Current measured boundary

On the current audit machine, the Python streaming sign-candidate pass over
the first 10 IDR slices of `deadline_cif_q22_g1_600f.h264` (16,768,616 bytes)
selected 1,096 keyed positions in 1.997 seconds (5.008 slices/s). Its bounded
selector retained only the requested positions and the observed working set
stayed below 45 MB during a full-file scan. This is evidence for bounded
candidate-selection memory, not a realtime claim: 5.008 slices/s is below a
30 FPS camera target and the measurement excludes native patch/write, proof,
and decoder validation.

### Latest end to end negative result

The Python path is not a usable embedding path yet. On the audit machine, a
one-byte blind proof payload (1,072 bits) was scheduled and patched into
`foreman_cif_q18_g1_300f.h264` (300 all-intra frames) in 280.579 seconds.
The patcher reported all 1,072 positions applied and preserved the source
byte length (3,551,610 bytes), but the resulting stream was not valid: FFmpeg
reported H.264 macroblock/CAVLC errors when run with `-xerror`, and blind
verification returned `valid: False` after 276.849 seconds (557.428 seconds
total). A normal FFmpeg invocation can conceal these errors while returning
zero; it is not an acceptable decoder acceptance test.

`patch_selected_sign_positions_streaming` now validates its temporary output
with `ffmpeg -v error -xerror` before atomically publishing it. A decoder
error therefore aborts the operation and removes the temporary file. This is
a fail-closed safety gate, not a repair for the legacy Python multi-block CAVLC
patcher. That result does not describe the native C++ path below. Native
functional E2E evidence is recorded separately and still does not establish
camera or edge performance.

### Native Linux fixture E2E (2026-09-24)

On Ubuntu 24.04 x86-64 (GCC 13.3, OpenSSL 3.0.13, FFmpeg 6.1.1), the current
native C++ core built successfully and CTest passed 1/1 in 44.30 s. The native
CLI embedded the 16-byte `native-linux-e2e` payload into
`foreman_cif_q18_g1_300f.h264` (300 all-intra frames), producing a 3,551,610-byte
stream. Blind extraction recovered the exact payload with the correct key;
strict `ffmpeg -v error -xerror` decode passed and the wrong key was rejected.
This closes the Linux functional fixture gap, not the edge-device acceptance
gate: no Linux camera, ARM target, or target-edge performance measurement was
part of this run. The full Groth16 proof-bearing physical camera E2E remains a
separate development-host result.

### Native header traversal baseline

The native `zkstego_idr_inspect` tool scanned the 600-IDR
`deadline_cif_q22_g1_600f.h264` fixture in 501.974 ms on the audit machine.
It parsed the stream's SPS/PPS and all IDR headers, selected parameter sets,
parsed the first I-macroblock, and decoded its first luma CAVLC 4x4 residual
block. It did not traverse later macroblocks or residual blocks, select blind
candidates, patch signs, or validate an output decoder. This is a functional
and performance baseline for one native residual block per IDR only; it does
not establish a realtime steganography claim.

The native library now also has a luma-I4x4 macroblock traversal primitive. It
uses CAVLC's four coded-8x8-group order, derives `nC` from already decoded
left/top 4x4 neighbours, and has unit coverage for empty coded blocks. The
implementation additionally has regression coverage for the first-level
adjustment required by H.264 9.2.2 and the empty `nC=4..7` coeff-token
(`1111`). These two details are essential because an incorrect level adjustment
can change subsequent suffix lengths, while a missing empty-block token
desynchronizes the rest of a macroblock.

`zkstego_idr_inspect --macroblock` exercises this primitive against every
IDR's first macroblock. An earlier luma-only run on
`foreman_cif_q18_g1_300f.h264` reached 300/300 first luma macroblocks in
135.755 ms. The current full-residual diagnostic reaches 300/300 first
macroblocks, including ChromaDC and all eight ChromaAC blocks. The prior NAL
123 ChromaAC failure was traced to 12 incorrect `nC=0..1` `coeff_token` rows
in the native Table 9-5(a) copy, not to a constant boundary-context rule.
The corrected table is compared programmatically with FFmpeg's canonical
Table 9-5 data and covered by per-row regression tests for `TotalCoeff=13..16`.

### Full-slice traversal evidence

The native reader now traverses the entire locked IDR slice, including mixed
I4x4 and I16x16 macroblocks, I16x16 luma DC (16 coefficients), I16x16 luma
AC (15 coefficients), 4:2:0 ChromaDC/ChromaAC, and raster neighbour state.
The I16x16 DC context follows FFmpeg's `pred_non_zero_count` mapping through
the normal luma block-zero neighbours; it is not a separate DC-grid context.
At completion the reader requires a valid `rbsp_stop_one_bit` followed only
by zero alignment bits.

On `foreman_cif_q18_g1_300f.h264` (3,551,610 bytes, SHA-256
`867CC0C68BBA4461E5699C1214236DF5CC75C658398C85F2E11BCCC11935DF57`), the
Release CTest traversed all 300 IDR slices, each with 396 macroblocks:
**118,800 macroblocks total**. It additionally asserts that I16x16,
ChromaDC, and ChromaAC paths were encountered. The command
`zkstego_idr_inspect ... --slice` independently reported the same counts and
the source fixture passes `ffmpeg -v error -xerror`. This proves native reader
coverage for that pinned fixture; it does **not** prove a generic H.264 reader.
Rewrite, blind extraction, and decoder-valid output have separate fixture E2E
evidence below; target-edge realtime operation remains a release gate.

### Length-invariant sign rewrite evidence

For each residual block with one or more trailing ones, native traversal emits
only the first trailing-one sign flag as its candidate. That bit follows the
`coeff_token`, so changing it cannot alter `TotalCoeff`, `TrailingOnes`, level
coding, run coding, or the RBSP bit length. Candidate identity is the tuple
`(NAL index, macroblock address, residual category, block index, RBSP bit
offset)`, deliberately using RBSP rather than EBSP offsets because regenerated
emulation-prevention bytes may move EBSP positions.

The native regression flips one such candidate, verifies the output bit and
the complete ordered candidate map after a full reparse, and CTest passes.
Independently, `zkstego_idr_inspect --flip-first-sign <new-file>` flipped NAL
3 / macroblock 0 / RBSP bit 91 in the pinned fixture; its temporary output had
3,551,610 bytes and SHA-256
`E1415CCC2CCA3DC13B7D71225401E8C9FEEEFF1BC493A119FE406EA5E138A7F0`.
`ffmpeg -v error -xerror -i <new-file> -f null -` returned successfully.
This historical test is strict-decoder evidence for **one** native sign rewrite
only. The keyed multi-bit authenticated frame, extraction, and stream path have
separate E2E evidence below. This single-bit test itself does not establish
target-edge realtime performance.

### Canonical blind schedule (implementation gate)

The next native channel must use this single schedule contract; an extractor
derives it from the stego stream itself and never receives positions or a
sidecar. A candidate is exactly one parsed trailing-one sign bit per residual
block, with identity serialized as ASCII:

```text
<nal_index>:<macroblock_address>:<category>:<block_index>:<rbsp_bit_offset>
```

where `category` is `0=LumaDc`, `1=Luma4x4`, `2=ChromaDc`, or `3=ChromaAc`.
For a 32-byte secret `K`, the ordering score is the 32-byte HMAC-SHA-256
digest of that serialization under
the literal ASCII bytes `blind-native-cavlc-v1`, followed by one NUL byte and `K`.
Candidates are sorted lexicographically by
`(score, serialized identity)`, and the first `required_bits` candidates carry
payload bits in that order. The framing layer must authenticate and length-bind
the payload before embedding, so a wrong key produces an authentication failure
rather than a plausible message.

The native selector now has fixed candidate serialization, HMAC-score and
wrong-key order vectors. The `(score, identity)` tie fallback is deterministic;
creating a real SHA-256 HMAC collision for a runtime vector is not a feasible
test strategy. `embed_keyed_cavlc_sign_bits` and
`extract_keyed_cavlc_sign_bits` now apply this schedule directly to native
Annex-B/RBSP data. The regression uses the locked 300-frame fixture to embed
and recover 32 raw bits with the correct key, and shows a different raw
sequence with a fixed wrong key. These functions are not a message protocol:
they carry neither a length nor an authentication tag, so a caller cannot infer
wrong-key rejection from raw bits alone.

The native authenticated frame is now `version=1 | u16be(payload_length) |
payload | tag[16]`. Its tag is the first 16 bytes of HMAC-SHA-256 over the
preceding frame bytes, using the distinct derived HMAC key composed of the
literal ASCII bytes `blind-native-frame-v1`, one NUL byte, and `K`. The
receiver obtains the fixed 3-byte header first, validates the configured length
bound, then derives the longer schedule prefix and verifies the tag. Tests on
the locked fixture recover a correct-key payload and reject a wrong key and a
modified payload bit; an actual CLI E2E output also passes FFmpeg strict decode.
This authenticates a byte payload, including a serialized proof if supplied;
it does not itself generate or verify a ZKP, encrypt the payload, prevent frame
replay, establish Python parity, or prove realtime/production readiness.
The segmented native framing uses this same authenticated payload and inherits
those limitations. The current `payload_verify.circom` relation is exactly:

```text
h = SHA-256(message)
c = SHA-256(h || secret_key)
public signals = (h[256 bits], c[256 bits], message_length)
private witness = secret_key[256 bits]
```

`src/zk_proof.py` recomputes these public signals from the recovered message
and the supplied key before calling `snarkjs verify`. Consequently the camera
E2E proves that the recovered message and supplied key satisfy this circuit.
The Phase 1 real-proof test also changes only public `message_length` and
confirms verification rejects that proof under the altered signal. This does
not prove the source of the key, and it does not bind the proof to the
carrier video's bytes, decoded frames, camera identity, capture time, or a
session. A deployment verifier must obtain the expected public commitment from
a trusted policy/issuer if it needs to distinguish an authorized key from a
self-selected key. A proof-to-video claim would additionally need a canonical
video/session commitment included in the circuit's public statement and
recomputed by the verifier. The current circuit, native HMAC frame, and HTTP
adapter do not implement that extension. Do not describe this as video
attestation or camera-origin proof.

The proof cost matters to that design choice: physical-camera run 24 measured
Groth16 proof generation at 4,016.427 ms, explicitly outside capture. That is
about 120 times a 33.3 ms frame interval at the requested 30 FPS, so these
measurements do not support per-frame proof generation on the tested host,
much less on an edge device. Binding one proof to a completed stream would
instead require a canonical carrier commitment invariant under the selected
CAVLC sign edits, recomputation by the blind verifier, and post-capture or
two-pass proof construction; none is implemented or benchmarked here.
`benchmark/results/realtime_camera_runs_20260924.json` records the measured
proof time and its off-capture-path status.

### Native HTTP adapter and current E2E evidence

`src/api/native_handlers.py:create_native_app` connects the bounded FastAPI job
service to `zkstego_blind_bits`. The embed job uses native authenticated CAVLC
sign rewriting; the extract job is blind and downloads the recovered bytes as
an authorized, one-time artifact. Source uploads are removed after processing;
generated artifacts are consumed on download and expired by a ten-minute
default TTL sweeper. Aggregate multipart body size and total body-read duration
are bounded before a job slot is reserved. An OS-backed exclusive lease rejects
a second API process on the same work directory; startup recovery fails persisted
queued/running jobs and removes their uploaded/partial files. The key is provided to the child through
stdin, never as an argument or a temporary key file. Embedding sends the
payload hex through the same pipe as a second line using
`embed-stream-auth-stdin`; the job adapter selects IDR-local candidate schedules
with `ZK_STEGO_MAX_BITS_PER_IDR`, so payload bytes do not appear in the process
command line. The file-job CLI path still reads each completed upload into
memory; only the WebSocket path below uses the incremental NAL reader. Neither
path has yet established target-edge frame latency.
The native app disables the legacy Python proof-verification endpoint rather
than silently mixing data planes: HMAC authentication of bytes is not ZKP
verification.

On 2026-09-24, `uv run --with-requirements requirements.txt --with httpx python
src/runtest/test_native_http_channel.py` passed against the committed 300-frame
Foreman fixture and the locally built native CLI after wiring the handler to
the stateful IDR-session CLI. It
submitted an HTTP embed job, downloaded a same-size H.264 result, passed
`ffmpeg -v error -xerror`, extracted the exact test payload through HTTP with
the correct key, and failed the wrong-key extraction job without exposing a
payload artifact. The same test command now also runs the native stdin/stdout
pipe round trip, validates wrong-key rejection and strict FFmpeg decode, and the
native CTest covers 3-byte/4-byte split markers and NAL-size rejection. The
stdin/stdout test uses a buffered fixture, not a live camera source. There is
now an authenticated WebSocket channel at `/api/v1/stream` that relays raw
Annex-B chunks through that native pipe. It shares the API worker/queue
semaphore, limits each binary message to 1 MiB, total input to the configured
upload cap, chunk count to 100,000, and session duration to one hour by default.
Clients send an initial JSON operation (`embed` or `extract`), raw Annex-B
binary messages, then `{"type":"end"}`. Embed sends `complete` only after
successful child exit; extract returns a payload only after native HMAC
verification. Clients must treat premature disconnect or `error` as failure.
The key/payload cross this authenticated connection, so deployment requires
TLS. A real loopback Uvicorn/WebSocket TCP fixture E2E and physical
camera-through-WebSocket proof E2Es now pass; run 19 measures capacity, quality,
p50/p95, CPU/RAM, strict decode, and zero drops on the development host. These
host measurements do not verify edge performance. The Groth16 proof is for the
message/key public-signal relation and is verified after extraction; it is not
a proof that the payload commits to the camera video. Target-edge realtime and
production acceptance remain unmet.

### Physical webcam HTTP run (2026-09-24)

The hardware-gated `src/runtest/test_native_camera_http.py` was run against an
attached DirectShow UVC webcam. FFmpeg enumerated 352x288 as a
supported mode at 30 FPS. A three-second capture encoded Baseline/CAVLC,
all-intra, YUV420P; FFprobe counted 91 frames (38,534 H.264 bytes) and reported
25/1 average frame rate. Measured on this host: capture command wall time
4.779s; HTTP native embed job 0.275s; HTTP blind extract job 0.483s. The output retained the input byte length,
passed strict FFmpeg (`-v error -xerror`, exit 0), recovered `cam-proof-v1`
with the right key, and returned a failed extraction with the wrong key. The
capture was held in a temporary directory and removed after the test.

This is a successful physical-camera-to-HTTP fixture run, but it captures a
short clip before submission; it is not a live ingest/forwarding stream and its
job wall times omit the three-second capture/buffer interval. The observed
25/1 FFprobe rate differs from the requested 30 FPS mode and should not be
treated as measured realtime capture throughput. It does not
establish sustained FPS, p50/p95 under load, CPU/RAM, edge-device performance,
or actual ZKP generation/binding. The configured camera mode is 30 FPS while
the separate locked fixture was 25 FPS; camera-encoder compatibility must
remain scoped to the verified encoder options above.

### Direct camera -> WebSocket -> native stream E2E (2026-09-24)

The hardware-gated `src/runtest/test_native_camera_http.py` path fed a
DirectShow UVC camera's FFmpeg Baseline/CAVLC output directly from a live pipe
into `/api/v1/stream`, with no video file upload. It asserted that output bytes
arrived before the camera pipe reached EOF, then ran strict FFmpeg decode and
blind extraction over the same WebSocket channel. The initial HMAC-only
baseline produced
151 source and 151 stego frames at 352x288, 62,432 bytes on each side; FFprobe
reported `avg_frame_rate=25/1`, and strict decode exited 0. Correct-key extraction
matched `live-camera-proof`; wrong-key extraction returned
`payload_not_authenticated`. Three independent five-second camera runs each
produced 151 source/stego frames and passed strict decode. Startup until first
pipe bytes ranged 1.526–1.671 s; active pipe arrival rate was 29.692–29.881
frames/s, while launch-to-EOF throughput including startup was 22.396–22.910
frames/s. First native output arrived 1.418–2.081 ms after the first input
chunk. Native C++ measured p50 2.187–2.494 ms and p95 2.438–3.046 ms for only
7–9 IDR segments modified before payload completion. Comparing decoded source
and stego YUV420 frames gave full-video PSNR 60.5273–63.6297 dB, minimum
modified-frame PSNR 44.9360–46.2062 dB, mean luma SSIM 0.99998967–0.99999200,
and 142–144 identical frames per run. Native-child peak RSS was
5,484,544–5,505,024 bytes; recorded CPU time was 0.015625–0.046875 s across
approximately 6.7 s per process. This excludes API and FFmpeg camera-encoder
resources, and process wall time includes waiting for camera startup/input.
Per-run raw measurements are in
[`realtime_camera_runs_20260924.json`](../benchmark/results/realtime_camera_runs_20260924.json).

To collect reproducible hardware measurements, set `ZK_STEGO_CAMERA_NAME` to
the DirectShow camera name and run
`uv run --with-requirements requirements.txt python -m benchmark.realtime_camera_recorder --duration 60`.
The runner executes the physical-camera E2E and atomically appends structured
metrics only after all checks succeed. It preserves prior records; `--results`
can choose another artifact. The JSON includes camera startup and arrival-rate
timing, strict decoder status, proof and negative-check results, decoded
quality, native/process-tree resource samples, and stream backpressure counters.
Each new record additionally captures the exact pinned libx264 Baseline/CAVLC
camera-encode parameters, camera device name, host OS/architecture/CPU/RAM,
Python and FFmpeg versions, and native CLI path plus SHA-256 digest. Older runs
are preserved as-is rather than retroactively assigning unobserved metadata.
This is host-specific evidence, not a performance claim for a separate edge
target.

The same E2E was then repeated three times with a real Groth16 payload instead
of the earlier short application-bytes-only baseline. Each message was packed
with its 129-byte compressed proof, embedded in the camera stream, blind
extracted, decompressed, and verified using public signals recomputed from the
recovered message and key. All three proofs verified; wrong-key extraction was
rejected and strict FFmpeg decode passed. Prove time was 4.344–9.426 s before
camera capture; verify-after-extraction was 2.217–2.268 s. Those costs are not
on the measured capture path, so the test does not demonstrate live proof
generation or verification at camera frame rate. Proof-bearing runs modified
39–47 IDR segments; their full-video PSNR was 56.8673–59.2692 dB, minimum
modified-frame PSNR 44.0153–46.0138 dB, and mean luma SSIM 0.99995448–0.99996143.
An additional negative E2E check confirmed the recovered Groth16 proof fails
verification when either the public key-derived commitment or recovered
message is changed; these checks are independent of the outer HMAC rejection.

A 60-second proof-bearing camera soak then delivered 1,801 source and 1,801
stego frames (773,750 bytes each) with no frame-count loss; the active arrival
rate was 29.976 frames/s. The first output arrived 2.068 ms after the first
pipe chunk. Native patch p50/p95 across 34 payload-bearing IDRs was
2.190/2.756 ms. Strict decode, correct-key extraction, Groth16 verification,
wrong-key rejection and changed-message rejection all passed. Decoded quality
was 67.2664 dB full-video PSNR, 41.7642 dB minimum modified-frame PSNR and
0.99999655 mean luma SSIM. Native child peak RSS was 5,537,792 bytes and CPU
time 0.234375 s over a 61.845 s process lifetime; this still excludes API and
camera-encoder resource use. The exact run is `run: 8` in the JSON artifact.

A repeat 60-second run with process-tree sampling recorded 1,801 input/output
frames, 29.986 frames/s active arrival, native patch p95 2.597 ms (73 patched
IDRs), and the same strict decode/proof/negative-check passes. Full-video PSNR
was 70.3741 dB, minimum modified-frame PSNR 43.6291 dB and mean luma SSIM
0.99999318. The capture process tree (TestClient API process, native CLI and
FFmpeg encoder) peaked at 138,465,280 bytes RSS and accumulated 11.4375 CPU
seconds during 61.863 s. The Groth16 prover and after-capture verifier were
outside this sampler. The exact data is `run: 9` in the artifact.

A further 60-second proof-bearing run through the recorder captured and emitted
1,801 frames with no loss at 29.987 frames/s active pipe arrival. Backpressure
counters recorded 916 input chunks, 916 awaited native-stdin drains, zero
dropped chunks and zero observed native-stdin user-space buffer bytes; input
chunks were at most 4,118 bytes. Strict decode and correct-key, wrong-key,
changed-message and Groth16 verification gates all passed. Native patch p95 was
2.7003 ms across 46 payload-bearing IDRs; decoded full-video PSNR was 67.8012
dB, minimum modified-frame PSNR 44.8819 dB and mean luma SSIM 0.99999649. The
capture process tree peaked at 139,341,824 bytes RSS with 10.765625 CPU seconds
over 61.860 s; native-child RSS was 5,935,104 bytes. The exact data is `run: 12`
and was appended automatically only after the E2E gates passed.

After adding explicit CAVLC capacity counters, another five-second proof-bearing
camera run passed the same strict-decode, correct/wrong-key, changed-message and
Groth16 checks. It emitted all 151 camera frames at 29.780 frames/s active pipe
arrival. The 150-byte packed message+proof became a 169-byte authenticated frame
(1,352 embedded bits including the native protocol header and HMAC); 22
payload-bearing IDRs reported 1,408 aggregate candidate-capacity bits under the
64-bit/IDR cap. This is the capacity consumed through completion, not the
camera mode's maximum capacity. Full-video YUV420 PSNR was 62.484 dB, minimum
modified-frame PSNR 50.3395 dB and mean luma SSIM 0.99994645. Strict FFmpeg
decode exited 0; native segment p50/p95 was 6.8882/9.0552 ms over those 22 IDRs.
Native child peak RSS/CPU was 5,722,112 bytes/0.171875 s; sampled API+FFmpeg+
native process-tree peak RSS/CPU was 142,209,024 bytes/1.75 s over 6.854 s.
Groth16 proving (4.249 s) occurred before capture and verification (2.215 s)
after extraction, so neither is included in camera-rate processing. The exact
record is `run: 13` in the camera JSON artifact.

A 60-second repeat with the new capacity counters emitted 1,801 of 1,801
frames at 29.987 frames/s active arrival, with no dropped chunks and strict
FFmpeg decode exit 0. Correct-key blind extraction recovered the packed
message/proof, Groth16 verification passed, and wrong-key/changed-message checks
failed as intended. The authenticated frame consumed 1,352 bits from 1,408
aggregate candidate-capacity bits across 22 payload-bearing IDRs. Segment
p50/p95 was 6.9222/7.9279 ms. Decoded full-video YUV420 PSNR was 73.6628 dB,
minimum modified-frame PSNR 50.1418 dB and mean luma SSIM 0.99999402. Native
child peak RSS/CPU was 5,611,520 bytes/0.359375 s; process-tree peak RSS/CPU
was 146,481,152 bytes/13.109375 s over 61.847 s. Proof generation (4.252 s)
and post-extraction verification (2.267 s) were outside camera processing.
The exact recorder output is `run: 14`. It extends the host soak evidence but
does not establish performance on an independent edge device or multi-hour
stability.

Run 15 used the same 60-second camera profile and added the full-stream capacity
scan. It passed strict decode, frame-count, blind extraction, proof verification,
and all negative-key/message checks; all 1,801 frames arrived at 29.976
frames/s, with zero dropped chunks. The complete source had 1,801 supported IDR
segments and 825,136 raw eligible sign positions. With the configured 64-bit
per-IDR cap, whole-clip capacity was 115,264 authenticated-frame bits (14,408
bytes, or up to 14,389 payload bytes after the 19-byte native frame overhead).
The live proof frame used 1,352 bits; its 22 payload-bearing IDRs had 1,408
aggregate candidate-capacity bits. Whole-stream analysis took 10.784 s after
capture and is not a live-path cost. Full-video PSNR/mean luma SSIM were
70.7795 dB/0.99999241 (minimum modified-frame PSNR 47.5042 dB); native patch
p50/p95 was 7.2609/8.8021 ms. Native child peak RSS/CPU was
5,623,808 bytes/0.34375 s; the sampled capture process tree was
146,358,272 bytes/14.0625 s over 61.869 s. Groth16 proving (4.289 s) and
verification (2.214 s) were outside capture. The result is `run: 15` in the
camera JSON artifact. This remains host evidence at 352x288, not validation on
an independent edge target or proof of multi-hour stability.

Run 16 added per-IDR service timing for the same 60-second camera mode. It
again captured/emitted 1,801/1,801 frames at 29.972 frames/s active arrival,
with zero dropped chunks, strict decode, proof verification, and correct-key /
wrong-key / changed-message checks passing. Whole-stream capacity remained
115,264 bits over 1,801 IDRs; 885,366 raw sign candidates were eligible, and
the post-capture scan took 11.048 s. The all-IDR service samples covered all
1,801 NALs: p50/p95 was 0.0179/0.0298 ms. Only 22 IDRs (1.22% of the clip)
carried payload, so their separate patch-process p50/p95 was 7.5343/8.2745 ms;
the lower all-IDR p95 is not a substitute for that tail figure. Decoded quality
was 70.4466 dB full-video PSNR, 48.5958 dB minimum modified-frame PSNR and
0.99999296 mean luma SSIM. Native child peak RSS/CPU was 5,681,152 bytes /
0.328125 s, while the capture process tree was 147,927,040 bytes / 12.171875 s
over 61.867 s. Proof generation (4.209 s) and verification (2.223 s) were
outside capture. These service metrics exclude input wait and network send;
this is still a development-host result, not an independent edge measurement.
The recorded run is `run: 16`.

Physical-camera run 21 adds an arrival-to-arrival NAL metric to the 60-second
host proof E2E. The harness timestamps each camera FFmpeg stdout read in 1 KiB
chunks and each corresponding WebSocket TestClient output chunk, then pairs
NAL completions by Annex-B order and verifies NAL types/counts agree. For 5,404
NALs, `ffmpeg_stdout_nal_completion_to_websocket_client_nal_completion` p50/p95
was 2.2267/125.257 ms. The high p95 tail is a measured concern, not a claim of
uniform few-millisecond latency. Because the receiver is Starlette's in-process
TestClient, the metric excludes TCP/TLS transport and sensor-exposure delay; it
must not be called camera sensor-to-output latency. Run 21 otherwise passed
strict decode, frame accounting (1,801/1,801 at 29.977 active FPS), zero-drop
flow checks, and proof/key gates. The artifact is
`benchmark/results/realtime_camera_runs_20260924.json`.

Physical-camera run 2 in
`benchmark/results/realtime_camera_tcp_decomposed_20260924.json` repeats the
60-second E2E through Uvicorn and a real loopback TCP WebSocket. It passed all
capture, bounded-flow, strict-decode, blind extraction, proof and negative-key
gates with 1,801/1,801 frames at 29.979 active FPS and zero dropped chunks.
Across 5,404 NALs, end-to-end host loopback TCP p50/p95 was
1.2775/128.5626 ms. Client camera-read-to-send-return p95 was 0.2847 ms; client
send-return-to-output-receive p95 was 128.4907 ms. Server native stdin
write+drain p95 was 0.0321 ms and native stdout-to-WebSocket-send p95 was
0.2052 ms. Payload-bearing native patch p95 was 12.4047 ms. This localizes
the measured tail after the synchronous client's send returns and before that
client receives output, outside the measured server send/drain intervals; it
does not distinguish OS/TCP delivery scheduling from client receiver
scheduling. It is not LAN/TLS or sensor-exposure-to-output latency. The
in-process TestClient run 21 and chunk-size experiment remain historical,
separately labeled measurements rather than TCP data.

The async loopback harness then measured NAL timing distributions and server
stdout-read wait on real camera captures. Reducing DirectShow `rtbufsize` from
64 MiB to 1 MiB / 256 KiB yielded TCP NAL p95 127.5855 / 127.4311 ms; the
256 KiB run retained 1,801 frames with zero drops and all strict-decode/proof
gates passing. Its input/output NAL interarrival p95 was 125.7893 / 126.1756 ms,
server native stdout-read wait p95 was 145.1017 ms, and server stdout-to-send
p95 was 0.1992 ms. The 64 MiB observation had input/output interarrival p95
126.1165 / 126.707 ms and end-to-end p95 128.0479 ms. Because each was a
different camera scene, the sub-millisecond end-to-end difference is not a
causal result. The input/output cadence similarity and long native-output
read wait are consistent with bursty DirectShow/FFmpeg input being a major
contributor, but do not prove it without sensor timestamps or repeated,
controlled capture. The harness now caps this input queue at 256 KiB to limit
potential backlog; verify this does not drop frames on each target camera.

Run 22 extends that 256 KiB configuration to a 300-second physical-camera
soak. It captured/emitted 8,999/8,999 frames at 29.997 active FPS (29.869 FPS
including startup), with no dropped chunks; strict FFmpeg decode, correct-key
blind extraction, Groth16 proof verification, and wrong-key/changed-message
rejection all passed. Over 26,998 NALs, loopback-TCP latency p50/p95 was
1.299/127.9583 ms; input/output NAL interarrival p95 was 126.2041/126.8606 ms.
Native stdout-read-wait p95 was 145.5923 ms, while stdout-to-WebSocket-send
and stdin-write/drain p95 were 0.197/0.0337 ms. Payload-bearing patch p50/p95
was 8.5508/9.5462 ms over 22 IDRs, and all-IDR service p95 was 0.0384 ms.
Decoded quality measured 79.8169 dB full-video YUV420 PSNR, 48.5743 dB minimum
modified-frame PSNR, and 0.99999771 mean luma SSIM. Whole-stream candidate
capacity was 575,936 bits across 8,999 IDRs; its 54.902-second scan ran after
capture. The capture-stage process tree measured 259,338,240-byte peak RSS and
60.922 CPU seconds over 309.022 seconds; native-child peak RSS/CPU was
5,283,840 bytes/1.094 seconds. These resource figures exclude post-capture
analysis and proof generation/verification. The long soak confirms host
continuity but does not resolve the ~128 ms latency tail: camera timestamps are
absent, and loopback TCP is not sensor-to-output or target-edge measurement.
All raw per-run fields, identity data, and binary hash are in run 22 of
`benchmark/results/realtime_camera_runs_20260924.json`. Its reported frame
rate is default-sync raw-H.264 output cadence, not verified camera sensor FPS.

However, a separate capture-only diagnostic on 2026-09-24 makes the camera FPS
claim conditional. DirectShow raw YUYV422 passthrough produced 450 complete
frames in 60 seconds (7.5 FPS; completion interarrival p50/p95
128.3263/156.99 ms); MJPEG passthrough independently produced 450 frames
(129.989/155.3098 ms). A 20-second initial libx264 test emitted 150 frames in
each mode because it targeted FFmpeg's null muxer; it did not exercise raw-H.264
output duplication. The raw-H.264 comparison in the correction below revises
the interpretation of the requested 352x288@30 mode, which the current session
did not deliver at 30 source frames each second. This
conflicts with the earlier full E2E run counts, which had no reliable source
PTS and were taken in a separate session. Therefore the earlier ~30 FPS
arrival-rate measurements prove the output counts of those runs only, not a
guaranteed 30-FPS camera acquisition capability. Inspect/lock exposure and
driver mode, and pair source-frame counts/timestamps with encoded NALs before
using those figures for acceptance. Exact commands and outputs are recorded in
`benchmark/results/realtime_camera_capture_rate_diagnostic_20260924.json`.
This diagnostic suggests the present ~128–157 ms frame/NAL tail can originate
at capture under current conditions; it does not prove sensor-exposure latency.
The diagnostic host is an ASUS TUF Gaming F15 FX507ZM running Windows 11 Pro
build 26100. Its built-in UVC camera (`USB\VID_13D3&PID_56A2&MI_00`) uses
Microsoft's `USB Video Device` driver, version 10.0.26100.9444, INF
`usbvideo.inf`. A read-only `IAMCameraControl::GetRange/Get` query reports
auto exposure enabled at −6 log2 seconds (1/64 s), with a manual range of −8
to 0 (1/256 s to 1 s); no `Set` call was made. The reported value is shorter
than 1/30 s, so simple long-exposure throttling is not established as the cause
of the low rate. This property is not a sensor timestamp or a measurement of
actual integration time; driver delivery/pacing and other device timing remain
to be isolated. The recorded hardware identity and query are included in the
diagnostic JSON so camera rate results are not generalized across UVC devices.

### Camera frame-rate accounting correction

The raw-H.264 muxer comparison later established that default output
synchronization can create synthetic frames: on a 20-second test it emitted
600 encoded frames from 150 camera frames and logged 450 duplicates. With
`-fps_mode passthrough`, the same mode emitted 150 and logged no duplication.
The corrected full camera WebSocket/native E2E is run 24 in
`benchmark/results/realtime_camera_runs_20260924.json`: 450/450 frames, 7.608
active FPS, zero dropped chunks, strict FFmpeg decode and all proof/key checks
passing. Its loopback latency p50/p95 was 1.9672/147.3311 ms; native payload
patch p50/p95 was 7.3922/9.8505 ms. This measured host camera did not satisfy
30-FPS acquisition. All earlier ~30-FPS E2E frame counts used default raw-H.264
synchronization and are output-frame counts, not evidence of sensor acquisition
rate; historical JSON remains unchanged, while the harness and new records now
explicitly require passthrough. The capture-only raw YUYV/MJPEG diagnostics and
raw-H.264 command evidence are in
`benchmark/results/realtime_camera_capture_rate_diagnostic_20260924.json`.

After this harness change, the quick suite passed 75/75 and the full Python
suite passed **95/95**. Phase 11's 22/22 now includes a command-level assertion
for `fps_mode=passthrough` and a recorder rejection test for any other mode;
Phase 12 loopback fixture E2E passed 5/5. The real-camera run 24 above is the
hardware E2E evidence for the corrected frame-counting behavior.

An isolated 16 KiB camera-pipe-read experiment is stored separately in
`benchmark/results/realtime_camera_chunk16k_experiment_20260924.json` (run 1).
It passed the same 60-second camera, strict-decode, blind extraction, Groth16,
wrong-key, changed-message, quality, and bounded-flow gates: 1,801/1,801
frames, 30.002 active FPS, zero dropped chunks, and NAL pipe-to-TestClient
p50/p95 2.2803/77.1584 ms. Compared with run 21's 1 KiB chunks and
2.2267/125.257 ms, p95 is lower in this observation, but changing live scene
content and non-paired runs prevent attributing the difference to chunk size.
Native payload-bearing patch p50/p95 was 71.2413/75.0032 ms in this scene,
showing content complexity also affects patch timing. This remains a TestClient
measurement, not real TCP/TLS camera latency, and the high tail is unresolved.

Run 17 is a five-second repeat recorded after the full Phase 4/5/6/7/8/9
suite passed. It emitted 151/151 frames at 29.789 frames/s active arrival,
with zero dropped chunks; strict FFmpeg decode, blind extraction, proof
verification, and wrong-key/changed-message rejection passed. Full-video PSNR
was 59.7052 dB, minimum modified-frame PSNR 47.7635 dB, and mean luma SSIM
0.99988542. The native payload-bearing patch p50/p95 was 8.7398/9.557 ms over
22 IDRs; all-IDR service p50/p95 was 0.0211/8.9457 ms over 151 IDRs. Native
peak RSS was 6,471,680 bytes, while the sampled API+FFmpeg+native process tree
peaked at 141,099,008 bytes. The proof was generated before capture and
verified after extraction; this short repeat supplements, but does not replace,
the 60-second soak in run 16. The exact data is `run: 17` in the camera JSON.

Run 19 is the latest metadata-complete 60-second physical-camera soak. It
captured and forwarded **1,801/1,801 frames** at 29.979 FPS active pipe arrival
(29.409 FPS including 1.164 s camera startup), with zero dropped input chunks.
First output followed the first input chunk by 2.033 ms; this is not
sensor-exposure latency. Strict FFmpeg decode passed; correct-key extraction
matched and verified the 129-byte Groth16 proof, while wrong-key extraction and
wrong-key/changed-message proof checks rejected. Whole-stream candidate
capacity was 115,264 bits across 1,801 IDRs; 1,400,881 raw sign candidates were
eligible. The frame carried 1,352 authenticated bits using 1,408 candidate
positions across 22 patched IDRs. Payload-bearing patch-process p50/p95 was
9.0378/10.7122 ms; all-IDR service p50/p95 was 0.017/0.0362 ms. Decoded
YUV420 full-video PSNR was 72.7252 dB, minimum modified-frame PSNR 50.385 dB,
mean luma SSIM 0.99998796, and minimum luma SSIM 0.99821548. Native-child
peak RSS/CPU was 5,152,768 bytes/0.453125 s; sampled camera/API/FFmpeg/native
process-tree peak RSS/CPU was 141,774,848 bytes/11.328125 s. The post-capture
capacity scan took 13.648 s; proof generation (4.049 s) was before capture and
verification (2.126 s) after extraction. FFprobe reported no timestamped frames
for this raw Annex-B stream, so FPS above is wall-clock arrival rate, not a
PTS-derived rate. Full measurements and host/tool/binary metadata are in
`run: 19` of `realtime_camera_runs_20260924.json`. This is a host result, not an
independent edge-device measurement.

Run 20 repeats the 60-second proof-bearing camera path after switching the
client E2E to the public `ZKSnarkBridge.verify_proof_for_payload` API. It
captured/emitted **1,801/1,801 frames** at 29.974 FPS active arrival (29.328 FPS
including 1.325 s camera startup), with zero dropped chunks; strict FFmpeg
decode and correct-key extraction passed, and wrong-key extraction plus
wrong-key/changed-message Groth16 checks rejected. The 129-byte proof verified.
Full-stream capacity was 115,264 bits over 1,801 IDRs from 1,167,124 raw sign
candidates; 1,352 authenticated bits used 1,408 positions across 22 patched
IDRs. Payload-bearing patch p50/p95 was 8.9923/9.7913 ms; all-IDR service
p50/p95 was 0.0173/0.0366 ms. Decoded YUV420 PSNR was 72.7712 dB overall and
49.2416 dB minimum on a modified frame; luma SSIM mean/min was
0.99998695/0.99806717. Native-child peak RSS/CPU was 5,140,480 bytes/0.4375 s;
the sampled process tree peaked at 141,402,112 bytes and 11.46875 CPU seconds.
Proof generation (4.036 s) was before capture and verification (2.088 s) after
extraction; the capacity scan took 12.451 s after capture. As in run 19,
FFprobe had no timestamps for the raw Annex-B input, so FPS is wall-clock pipe
arrival, not PTS-derived FPS or sensor-to-output latency. Run 20 is still a
development-host result, not an edge-device benchmark.

The tested UVC device was re-enumerated with FFmpeg DirectShow
`-list_options true`: it exposes MJPEG and YUYV422 modes (including
352x288@30), but no H.264 mode. Therefore the camera E2E's locked
Baseline/CAVLC bitstream is produced by host `libx264` from the camera's
MJPEG/raw capture; it does not validate a camera's built-in H.264 encoder or
an edge-board hardware encoder. An edge deployment using this camera would
need to run and benchmark the pinned Baseline/CAVLC encoder on the target, or
use a different camera/encoder that exposes a verified compatible H.264
stream.

The existing circuit proves knowledge of the key for a public hash of the
message. It does not prove that the message describes, hashes, or originated
from the camera frames. The native HMAC frame authenticates extracted payload
bytes to the key, but does not authenticate every video bit or camera origin.
Thus this is real proof-carrying payload embedding and recovery, not a
zero-knowledge attestation of the video content or capture device.

These are development-host runs (multiple 5-second diagnostics and proof runs,
plus 60-second proof-bearing soaks), not a long-duration target-edge benchmark.
The historical pre-passthrough arrival rate is not source-camera FPS,
per-frame latency, or proof of production-sustained 30-FPS processing; the
corrected frame-accounting result below shows why. FFprobe on the raw Annex-B
stream reports 25/1 average rate, nominal rate near
60, no container duration, and zero timestamped frames. DirectShow advertises
352x288 at 30 FPS for this camera, and historical default-sync H.264 pipe
arrival was 29.692–29.987 encoded frames/s; later raw-H.264 comparison showed
that this path can include duplicated frames. These historical rates are not
sensor-acquisition FPS. FFprobe rates are not wall-clock observations because
the elementary stream carries no PTS. First-output timing starts from an FFmpeg
pipe chunk (which may contain multiple frames), not sensor exposure. Native
p50/p95 covers only payload-bearing patched segments, not every
pass-through frame or camera-to-output latency. Target-edge performance and
multi-minute/hour stability remain unmeasured; the 60-second process-tree CPU
and RSS figures include this test-host/API/FFmpeg/native stack but exclude
proof generation/verification and should not be projected to edge hardware;
realtime/production acceptance remains unmet.

### September 2026 diagnostic update

The `nC=0` versus `nC=2..3` ChromaAC discrepancy must not be fixed by a
constant frame-edge value. A controlled probe that seeded unavailable ChromaAC
neighbours with `2` made Foreman NAL 123 parse, but then made NAL 3 reject a
ChromaAC `total_zeros` value outside its 15-coefficient bound. The probe was
discarded. Comparing native rows against FFmpeg instead found the malformed
Table 9-5(a) entries and corrected the actual source of the desynchronization.

FFmpeg's CAVLC decoder calculates `nC` from its populated
`non_zero_count_cache`; it does not substitute a fixed edge context. Native
completion still requires macroblock-by-macroblock availability and cache
state matching for luma and each chroma component before any CAVLC token may
be rewritten. The full-slice reader now implements that cache for the locked
one-slice profile and remains fail-closed outside it.

The legacy Python public-API E2E test is also not an edge benchmark. It uses
sidecars and a full-file batch parser, so it cannot be used as evidence for the
required sidecar-free native edge data plane. On 2026-09-24 the complete Phase-5
`embed`/`verify` test finished successfully (2/2 Phase-5 cases); sampled Windows
working set for the full-suite test process reached approximately 2.7 GB during
that phase. This supersedes the earlier diagnostic note that described stopping
the same test before completion due to memory use.

## Blind extraction relationship

Blind extraction and realtime use the same sign-invariant candidate policy.
`src/blind.py` derives sign-only positions from the stego bitstream and secret
key. The native patcher must preserve this policy exactly; otherwise a stream
can be fast but cannot be extracted without a sidecar.
