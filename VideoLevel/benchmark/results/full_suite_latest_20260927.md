# Current full-suite result — 2026-09-27

Command: `py -3.12 src/runtest/run_all.py`

Exit status: **1 (failed)**. The runner reported **69/79 checks passing**, with
**2 skipped**. Do not interpret this as an end-to-end lattice-ZKP pass.

## What passed

- Phases 1–3 and 12–22 passed except for the runtime failures listed below.
- The newly registered pytest phases 19–22 passed **11/11** in the full run:
  strict decode gate 4/4, verified analysis context 2/2, retry contract 2/2,
  parser integrity 3/3.
- Phase 1 tests legacy Groth16 serialization/prove/verify helpers. This is not
  the lattice proof required by the project goal.
- Phase 14 tests LaZer host preflight and fail-closed behavior; it does not run
  a LaZer proof backend on this host.

## What failed or was skipped

- Phase 4 reconstruction failed because the parser refused untrusted offsets
  after heuristic recovery on the Foreman GOP8 fixture (first resync at MB 53).
- Phase 6 near-blind video verification and Phase 7's video operating-point
  check failed on parser integrity errors in the deadline fixture (first
  resync at MB 25 / bit 21,046).
- Phase 5 skipped both API/lattice-receipt checks because no benchmark asset
  was available to that phase.
- Therefore no full video embed → blind extract → lattice-proof verify flow was
  demonstrated by this run.

## Correctness change made during this run

The CAVLC encoder previously accepted a forced `TrailingOnes=1` for a block
whose coefficient vector had two trailing ±1 values. The emitted bits decoded
to a different coefficient vector. The encoder now rejects a supplied
`override_trailing_ones` unless it is an integer in 0–3 and matches the
coefficient block's actual trailing-one count. The Phase 20 test uses a
canonical block and checks that verified NAL context exposes only its actual
sign-bit carriers.

The H.264 decoding process applies the +2 `levelCode` adjustment at the first
non-trailing level when `TrailingOnes < 3`; this is specified in ITU-T H.264
and reflected in FFmpeg's CAVLC decoder. See the [ITU-T H.264 Recommendation](https://www.itu.int/rec/T-REC-H.264/en)
and [FFmpeg H.264 CAVLC decoder](https://ffmpeg.org/doxygen/8.0/h264__cavlc_8c_source.html).

## Remaining limitation

## Correction — run after the Intra16x16 DC nC fix

The preceding result above is historical; it predates the parser correction.
On 2026-09-27, `py -3.12 src/runtest/run_all.py` was run again after fixing the
Intra16x16 DC `nC` prediction and failing closed on DC decode errors. This run
finished with exit status **1: 75/79 passed, 2 skipped, 4 failed**.

- Phase 4 reconstruction: **5/5 passed**, versus 0/6 in the earlier run.
- Phase 22 parser-integrity gate: **4/4 passed**; the Foreman GOP8 first IDR
  parses as trusted with all 396 macroblocks and no integrity issues.
- Phases 19–21: **8/8 passed**.
- Phase 6 near-blind and Phase 7 regression still fail on
  `deadline_cif_q22_g1.h264`: the first IDR has a chroma-prediction parse
  error at MB 25 and later residual/chroma decode errors, so offsets are
  correctly rejected as untrusted.
- Phase 5 still skips 2 checks because no benchmark asset is available.
- FFmpeg decoded both `deadline_cif_q22_g1.h264` and
  `foreman_cif_g8_300f_b800k.h264` end-to-end with `-xerror`; parser rejection
  therefore reports a limitation of this parser, not proof that those inputs
  are invalid.

This remains a partial parser improvement only. The lattice ZKP is not yet
embedded and blind-extracted end-to-end, and the worktree changes are not
committed or independently reviewed.

## Deadline parser trace — follow-up diagnosis

Independent decode check:

```powershell
ffmpeg -v error -xerror -i data/encoded/deadline_cif_q22_g1.h264 -f null -
```

The command exited 0. `ffprobe` reports H.264 Constrained Baseline, 352x288,
`yuv420p`; this confirms the fixture is within the intended codec/profile
scope and is independently decodable.

Instrumenting the Python parser on the first IDR shows:

- MB24 header: bit 19,923 to 19,963; `mb_type=0` (I_4x4), `cbp=47`.
- It decodes 16 luma blocks, 2 chroma-DC blocks and 8 chroma-AC blocks,
  ending at bit 20,946.
- Parsing MB25 from bit 20,946 yields
  `intra_chroma_pred_mode=6` (outside the legal 0..3 range); heuristic scan
  then finds a plausible next MB at bit 21,046.

This narrows the first observed loss of alignment to MB24 residual parsing or
the boundary immediately after it, but does **not** identify which coefficient
table/context is wrong. The parser therefore remains untrusted for this input;
the trace is diagnostic evidence, not a successful extraction result.

## Root cause found and regression evidence

The MB24 trace showed the second chroma-DC block was the first non-roundtripping
block. H.264/FFmpeg's 2x2 chroma-DC `total_zeros` table maps TC=1 as
`1 -> 0`, `01 -> 1`, `001 -> 2`, `000 -> 3`; the local table incorrectly used
`00 -> 2`, which consumed one bit too few for the `001` code and shifted every
subsequent residual/MB boundary. The decoder table is corrected, and the
encoder now selects the same chroma-DC table when `nC == -1`.

Evidence after the correction:

- TDD was red before the fix: the normative `001` test case raised `KeyError`.
- CAVLC tables, nC prediction, chroma flags and parser trust-gate tests:
  **64 passed**; Python compilation succeeded.
- The 600-frame deadline fixture's first five IDRs each parsed as trusted,
  covering 396 macroblocks with zero integrity issues (about 0.43 s per IDR
  for the residual parser; Annex-B NAL scanning took about 9.28 s).
- The full runner was restarted to exercise later phases. Phase 4 had finished
  and the process advanced to Phase 5, but the Phase 5 API test selected the
  1,374-frame all-intra deadline asset and did not finish within the observed
  run. Its process reached about 10 GB working set while free physical memory
  fell to about 0.62 GB. I sent a soft interrupt to protect the workstation;
  memory recovered to about 10 GB free and no `test_p5_*` partial artifacts
  remained. Because the runner was interrupted before its summary, Phase 4's
  status from this run is not counted as a pass here, and Phase 5 is **not
  verified**.

The relevant CAVLC/parser regression set itself passed **64/64** before that
full-run attempt. A separate, bounded Phase 4 run is needed for fresh
reconstruction evidence. The resource profile also demonstrates that the
current whole-video analysis path is not suitable for real-time/edge use and
needs streaming or incremental processing before another long-clip attempt.

The custom parser remains untrusted on several real, independently
decodable H.264 fixtures. No proof has yet been embedded in a video and
blind-extracted for lattice verification. The worktree contains other
pre-existing edits and artifacts; this report does not imply they were
committed or independently reviewed.

## Bounded Phase 4 rerun — fresh evidence

On 2026-09-27, `py -3.12 src/runtest/test_phase4_reconstruct.py` was run by
itself against `foreman_cif_g8_300f_b800k.h264` after the chroma-DC correction.
It exited 0 with **5/5 passed**: output creation, Annex-B start code, patcher
skip bound and at least one successful patch, output-size bound, and successful
reconstruction stats. The test's cleanup removed its generated output. This
verifies the bounded Phase 4 fixture only; it does not override the interrupted
full-suite run or establish Phase 5 API/ZKP success.

## Phase 5 resource follow-up

The Phase 5 API test selects the highest-capacity candidate through the locked
operating contract / capacity scan, then calls the public `embed()` API on that
whole video. The observed selection was the 1,374-frame all-intra deadline
fixture. `load_or_build_video_analysis()` currently calls `H264BitstreamParser.parse()`
and `extract_all_idr_blocks()` and retains coefficients, per-frame verified
blocks/offsets, context maps and safe positions for the entire input in Python
objects. The previous run's ~10 GB working set therefore exposes an architectural
whole-video memory bottleneck, not merely the benchmark harness. Phase 5 remains
unverified until the API path can finish under a documented resource budget;
the immediate engineering requirement is incremental/streamed analysis and
patching (or a proven capacity-equivalent bounded working set), without
weakening the proof or replacing embedded proof bytes with a sidecar.

The repository's dedicated streaming-capacity scanner tests were also run with
their supported script entry point, `py -3.12
src/runtest/test_phase13_streaming_capacity_scan.py`: **11/11 passed**. The
initial `pytest` invocation collected no tests because these legacy phase files
use a custom `t_*` runner; it was not counted as test evidence. These 11 tests
validate chunk partitioning and honest capacity-report semantics only. They do
not validate proof embedding, visual quality, blind extraction, or API memory
use. The bounded Phase 4 output was confirmed absent after test cleanup.

## Shared residual-vector storage optimization

`extract_all_idr_blocks()` previously copied each nonzero luma coefficient
list into `coefficients`, while `frame_verified_data` retained the same decoded
block in its per-frame map. These structures are consumed read-only before the
embedder creates its own mutable coefficient working copies. The extraction
path now reuses the decoded list reference. A focused regression first failed
on object identity before the change and then passed; a second test confirms
the embedder leaves shared source vectors unchanged. Parser/cache/retry tests
passed **10/10**, Phase 3 safety/embed tests **8/8**, Ruff on the added test and
Python compilation passed. The touched files also pass Ruff with only the
legacy broad-exception rule excluded. Ruff reported six existing findings in
`pipeline.py`; unused imports/locals and import order were cleaned up during
review. One existing broad-exception lint finding remains in the direct
extraction helper and was left unchanged because it needs separate behavioral
analysis.

On this Python 3.12 runtime, a 16-element list occupies 184 bytes. Avoiding
one shallow list copy therefore saves at most 184 bytes per included luma
block, before allocator effects; the actual total depends on how many luma
blocks are nonzero. A real-video smoke test was started on the 150-frame
Foreman asset to verify source-vector immutability after an 11-byte embed, but
it did not finish within 30 minutes. It was interrupted cleanly with about
501 MB RSS and 1,382 CPU seconds; it produced no output file and is **not**
counted as a pass. Thus the aliasing contract is unit-tested and supported by
the embedder's copy-on-write implementation, but end-to-end compatibility and
measured whole-video RAM savings remain unverified. The runtime itself is an
additional strong indication that the current Python parse/filter/embed path
is not realtime.

## Video-only blind verification gap — source audit

The current `verify_near_blind()` implementation is explicitly near-blind,
not video-only: it loads `.manifest.json` and `.positions.json`, verifies the
signed manifest, and for the active ML-DSA path loads `.lattice.json` to obtain
the receipt needed to check the embedded commitment. The default `embed()`
path places `receipt.commitment()` in the video payload, not the complete
receipt. Therefore the current default path does **not** satisfy the goal's
requirement to extract and verify the complete proof from the video alone.
This is a direct source-code gap, independent of the Phase 5 resource failure.

The lightweight blind-analysis contracts were separately exercised using the
repository runners: Phase 16 **1/1**, Phase 17 **4/4**, and Phase 18 **1/1**.
They verify cache reuse, worker isolation and position/patchability contracts;
they do not remove the sidecar requirement or demonstrate proof extraction
from an arbitrary video without metadata.

## Latest CAVLC safety-filter optimization and reconstruction rerun

The safety filter previously encoded the unchanged source block again for each
candidate coefficient, even though every candidate in that block shares the
same source coefficients and CAVLC context. It now measures that source
bit-length once per block within one `get_safe_positions()` call and passes the
known value into the candidate check. The cache is call-local and keyed by the
global block identity, `nC`, and trailing-ones override; it is not reused across
videos or verification contexts. Candidate blocks are still encoded and
forward-decoded individually, and the original length must still match the
bitstream length when that safety rule is enabled.

The new regression was first run red (the method did not yet accept the cached
length), then passed after the implementation. Instrumentation verifies that a
candidate check performs only the modified-block encode when given the already
validated source length, while producing the same safety result as the
uncached path. The mismatch test verifies that a supplied source length which
does not match the NAL length is rejected. Selected related checks passed
**68/68** with pytest; the legacy Phase 3 and Phase 18 runners passed **8/8**
and **1/1**, respectively. Ruff passed on the new test file, Python compilation
passed, and `git diff --check` found no whitespace errors. Whole-file Ruff on
the pre-existing large `stego.py` reports 173 existing style/type findings;
that file was not auto-rewritten.

The real `foreman_cif_g8_300f_b800k.h264` Phase 4 fixture was then run twice in
this turn. The timed run exited 0 in **40.730 seconds** and passed **6/6**:
output creation, Annex-B signature, strict FFmpeg decode, patcher skip/patch
checks, size bound, and reconstruction statistics. Its output was cleaned up
by the test. This is one functional reconstruction test with a 12-byte test
message, not a repeatable performance benchmark: CPU/RSS, per-stage timings,
quality metrics and variability were not measured. It contains no lattice
proof and does not establish blind extraction, general H.264 compatibility or
realtime performance.

## Lattice backend preflight and probe regression

The current host's authoritative LaZer backend preflight was rerun with
`py -3.12 -m src.lazer_backend`. It exited normally but reported
`ready:false`, `docker_available:false`, no machine/CPU flags, and blocker
`docker_daemon_unavailable`. Therefore the pinned LaZer backend could not be
built or exercised here; no claim is made that the application's LaZer path
works on this host.

As a separate experiment, the pinned LNP22 feasibility probe was run uncached:
`go test -count=1 -v ./...`, `go test -race -count=1 ./...`, `go vet ./...`,
and `go mod verify` all exited 0. The six Go tests include an actual lattice
linear-relation proof round trip, rejection after changing the context, and
rejection of a mutated proof. This is evidence that the isolated probe and its
context-binding checks execute against the pinned Go module, not that the
application's fixed video relation is sound or implemented. The probe samples
its own relation/witness, has no independent cryptographic audit, and is not
connected to video embedding or blind extraction. The current operational
blocker for validating the LaZer implementation is still the unavailable
Docker/Linux execution environment; the wider ZKP/video-only requirements
remain engineering gaps, not environment-only blockers.

## Sidecar-free carrier re-derivation experiment

A first real-video attempt using the existing safe-position pool failed: after
embedding, the stego analysis selected a different coefficient in the same
block at carrier 33 (source candidate index 9 versus stego candidate index
10). This reproduced the known synchronization gap instead of hiding it.

The experimental blind contract now has an opt-in `stable_carriers_only` mode.
It deterministically selects at most one AC carrier per block, requiring
absolute coefficient magnitude at least 4 and excluding trailing-one slots;
it intersects the selected candidate with the source safe-position set and
then applies the existing patchability check. The `abs >= 4` threshold is
chosen so the carrier's LSB transition (`4 <-> 5`, or larger paired values)
does not turn it into zero or a trailing one. The mode is opt-in and does not
change the default production embedding path.

After that change, `py -3.12 -m pytest -q -s
src/runtest/test_video_only_blind_sync_integration.py` passed on the real
300-frame Foreman H.264 fixture in **80.58 seconds**. It embedded a deterministic
8-byte diagnostic payload, reconstructed the H.264 file, passed strict FFmpeg
decode, then re-derived exactly the same carrier sequence from the stego video
and extracted the exact payload. The output directory contained only the
`.h264` file; this test did not read a per-video positions/manifest/proof
sidecar. Phase 16, 17 and 18 custom runners separately passed **1/1**, **4/4**
and **1/1**; the stable-carrier unit check, py_compile, Ruff on the new test,
and `git diff --check` passed.

This is evidence for a low-level blind carrier synchronization path only. It
does not pass a lattice proof, does not exercise the public embed/API or blind
verifier, and does not establish robustness after remux/transcode or broad
stream compatibility. The test uses shared out-of-band sync key and known
payload length; in a complete system, proof framing/length and statement must
be discoverable/authenticated from the embedded protocol.

Docker Desktop was subsequently started and `docker info` reported a Linux
x86_64 engine. A fresh `py -3.12 -m src.lazer_backend` preflight now reports
the exact remaining host requirement as `avx512f_required`: Docker is
available, CPU flags include AES, but AVX-512F is not exposed to the container.
Thus the earlier Docker-unavailable result above is superseded for current
host state; the LaZer backend remains unexercised because this CPU environment
does not meet its AVX-512F requirement.

## Self-framing blind payload experiment

The low-level blind-video test now uses a fixed 14-byte envelope header:
`ZKVP` magic, version, payload kind, 32-bit payload length, and CRC-32 over the
prefix plus payload. The parser enforces an exact header, known version/kind,
16 MiB size limit, exact total length and checksum. CRC-32 only detects
accidental/corrupt framing; it is not an authentication primitive, and the
cryptographic proof must still be verified separately.

The real-video integration test embeds this complete envelope in H.264
residuals, reconstructs the video, runs strict FFmpeg decoding, reads only the
fixed header from the stego video, learns the body length, re-derives the
complete carrier sequence from that same stego video, and extracts/checks the
envelope. Its isolated output directory contains only the video. After fixing
the harness to pass the framed bytes (not the unframed test payload) to the
embedder, the final command
`py -3.12 -m pytest -q src/runtest/test_blind_payload_envelope.py
src/runtest/test_video_only_blind_sync_integration.py` passed **12/12** in
**100.77 seconds**. Ruff on the new test files, py_compile, and `git diff
--check` also passed.
Both suites are registered in `src/runtest/run_all.py` as Phases 23 and 24 so
the full runner can reproduce these gates.

This remains a low-level protocol experiment with an 8-byte deterministic test
message, not the application lattice proof: the public `embed()` API and
`verify_near_blind()` still use their existing manifest/positions/receipt
sidecars, the stable-carrier contract is opt-in, and no ZKP is embedded or
verified by this test. No CPU/RSS/quality distribution was collected; the
single-fixture elapsed time is diagnostic and is not realtime performance
evidence.

## Reusable video-only extraction entry point

The header/body procedure has been factored into
`extract_blind_video_payload(video_path, sync_key, contract)`, returning the
payload, derived metadata, envelope size and carrier count. It requires the
stable-carrier contract and reads no per-video sidecar. The low-level
`extract_bits_direct()` now also accepts an already parsed H.264 parser so the
header and body reads can share its NAL parse. A regression verifies that the
provided parser is reused rather than opening the video path again.

The real 300-frame Foreman integration was rerun after this refactor and passed
**2/2** in **130.83 seconds** (134.61 seconds measured around the Python
process). It still reconstructed and strictly decoded the stego stream and
recovered the framed diagnostic bytes through the new extraction entry point.
The previous run was 129.60 seconds, so this change did **not** produce a
measurable end-to-end speedup; the parser-reuse seam is structurally tested,
but the current workload remains slow and needs stage-level profiling. The
fast envelope/parser regressions passed **12/12**, and the new files compile
and pass Ruff. This API still extracts opaque payload bytes only; it does not
generate or verify a lattice proof, and the main application verifier has not
been switched to it.

## Public low-level sidecar-free embed/extract pair

The experimental channel now also exposes `embed_blind_video_payload()`.
Given a cover, opaque payload bytes, sync key and explicit stable-carrier
contract, it frames the bytes, derives and patchability-checks carriers, embeds
in CAVLC residuals, reconstructs to a temporary H.264 file, strictly decodes
that candidate with FFmpeg, then publishes only the video. It refuses an
existing destination and removes a failed temporary candidate. Paired with
`extract_blind_video_payload()`, this provides callable low-level embed and
blind-extract entry points without writing positions/manifest/proof sidecars.

The real Foreman 300-frame integration was switched from manually composing
the low-level pipeline to these two entry points. The run passed **2/2** in
**127.18 seconds**: the one video output strictly decoded, its envelope was
recovered without per-video sidecars, and the output-directory assertion found
only the H.264 file. Fast envelope, parser-reuse and overwrite-safety
regressions passed **13/13**; py_compile, Ruff on new tests and `git diff
--check` passed. These checks validate only an opaque 8-byte diagnostic payload
plus its framing, not proof generation or proof verification.

Important integration gap: the functions are not yet called by the public
`embed()`/HTTP workflow or `verify_near_blind()`. The default path still emits
ML-DSA receipt references with sidecars. There is no application ZKP payload
available to feed these experimental functions, and no statement/video
canonicalization or relation-verification gate has been implemented.

The newly registered runner phases were then invoked through
`run_pytest_phase()` itself. Phase 23 returned **3 passed, 0 failed** in
**132.04 seconds** on the real fixture, and Phase 24 returned **10 passed,
0 failed** in **0.44 seconds**. This verifies runner collection/exit handling
for these two phases; it is still only the diagnostic payload channel, not the
full application suite or a lattice-ZKP acceptance run.

## Real-video carrier-normalized digest check

Extended the 300-frame Foreman blind-channel integration test to independently
derive the stable carrier list from both the original cover and the resulting
stego video, assert that the lists are identical, and compare their canonical
H.264 digests after carrier normalization. The focused run
`py -3.12 -m pytest -q src/runtest/test_video_only_blind_sync_integration.py
-k stego_video_alone_rederives_carriers_and_extracts_payload` passed **1/1**
in **156.49 seconds**. The separate canonicalization unit suite passed **10/10**;
py_compile, Ruff and `git diff --check` also passed.

This is real-video evidence that the current stable carrier policy survives
embedding/extraction and that the carrier-normalized digest is invariant for
this fixture. The payload remains only an 8-byte diagnostic message with
framing; this test does not generate or verify a lattice proof, authenticate
the carrier policy or establish the application-level statement relation.

Adjacent contracts were also rerun: `test_video_zkp_contract.py` passed **7/7**,
the explicitly experimental statement-context relation suite passed **5/5**,
and the two fast sidecar-free integration checks passed **2/2**. These are
contract/unit results only; they do not change the ZKP/backend completion status.

## Prototype-proof labeling audit

The `LatticeZkReceipt` class and its direct test had stronger “transparent
lattice ZKP” wording than the project readiness claims allow. Updated the class
documentation and test heading to identify this as a research-only, unreviewed
SIS proof prototype; clarified that the ML-DSA signature authenticates the
receipt but does not upgrade the proof relation; corrected the README example's
stale `circuits_dir` comment. `py -3.12 src/runtest/test_lattice_zkp.py` still
passes **5/5**, now explicitly under “Research-only SIS proof prototype (not
an accepted backend).”

A Ruff check on the test file passes. A Ruff check covering the legacy
`src/lattice_pq.py` implementation still reports 10 findings, chiefly import
ordering, exception-type and quoted-annotation rules outside this documentation
change; that implementation is not reported as Ruff-clean. This labeling
correction does not improve the prototype's cryptographic assurance or enable
it in the application.

## Compact LNP22 proof serialization probe

Changed the fixed-relation test helper's proof wire representation from JSON to
`LNPF` v1: 11-byte header plus big-endian canonical `uint32` coefficients, with
strict magic/version/dimension/length/range checks. The current default context
has 12 limbs and yields exactly **33,803 bytes** (`11 + 33 * 256 * 4`), versus
the earlier JSON artifact's **57,415 bytes** (41.1% smaller encoding). This
reduces the payload requirement only; it does not reduce the proof itself.

Uncached `go test -count=1 -v ./...` passed **12/12**, including changed valid
context rejection, proof mutation rejection, malformed binary header/trailing
byte rejection, exact encoded-size assertion, handler-level setup/prove/verify,
and a subprocess `go run` CLI round-trip with changed-context rejection.
The CLI result records `prove_ms` and `verify_ms` for the cryptographic
operations separately; the integration test validates completion and context
rejection, but this run does **not** report a controlled latency benchmark.
`go run . -h` lists all three fixed CLI modes. `go test -race`, `go vet` and
`go mod verify` passed. The CLI/helper remains experimental and uses an
application-unrelated generated relation; no video embed/extract, quality or
application-ZKP verification result is claimed from this step.

## Experimental proof-in-video driver added (not yet run)

Added `benchmark/lnp22_context_probe/video_e2e.py`, which provides a strict
context/proof/payload envelope and an experimental `embed`/`verify` workflow
around the existing sidecar-free CAVLC payload channel. The intended run
generates a pinned relation, embeds the complete serialized proof in video,
strict-decodes, blind-extracts, recomputes carrier and normalized-video
digests, and verifies using only video bytes plus verifier configuration.
The relation is explicitly unregistered and generated for the experiment; the
proof does not establish the demo payload opening or encoder correctness and
is not wired into the production ZKP registry/API.

The 12 new tests pass; Ruff and Python compilation pass. They cover binary
envelope round trips, canonical context and statement mutation rejection,
field-length/truncation handling, sync-key validation and non-inheritance by
the Go child process, and refusal to overwrite outputs. These are unit/security
checks only. The driver has **not** been run on a real video, so there is no
proof-in-video, blind-extraction, decoder, image-quality or performance result
for this artifact. A fresh preflight observed about 3.4 GB free physical RAM;
an earlier whole-video analysis reached around 10 GB working set, so the
3,000-frame run was deferred rather than risking workstation exhaustion.

### Parser/cache reuse follow-up

Removed another avoidable allocation from the experimental video E2E path:
blind extraction now reuses the parser retained in the reconstruction context,
and canonical carrier hashing accepts the already parsed NAL stream and IDR
frame data. The probe passes that same cached analysis through source hashing
and blind verification, then clears process-local analysis between cover and
stego phases. The extraction path previously parsed the same input a second
time, and canonical hashing could parse it yet again.

Verification on 2026-09-27: the parser-reuse and LNP22 probe tests plus the
300-frame video-only blind-sync integration test passed **19/19** in **101.57
seconds**. Python compilation passed. Ruff still reports findings in legacy
dirty modules, so this is not a whole-module lint-clean claim. The live host
preflight reported **3.66 GB free of 23.63 GB RAM** after tests. This is a
memory-efficiency improvement, not proof the full proof-in-video run now fits;
that E2E remains unrun, and no full-size lattice proof has been embedded in a
video in this run.

### Segmented blind-channel transport smoke test

Added strict `ZKBC` v1 framing for a payload distributed over multiple H.264
segments. The frame records chunk index/count, total payload length, fixed
chunk size, and CRC-32 checks for each piece and the reassembled payload.
`src/blind_sync_streaming.py` splits at fixed frame intervals, rejects
non-exact (therefore non-IDR-aligned) boundaries, embeds one framed piece per
segment through the existing stable CAVLC channel, clears process-local
analysis after each segment, concatenates the Annex-B segments, and applies a
strict decode gate. Blind extraction reads the declared piece count from the
video and reassembles the exact payload without proof sidecars.

Real fixture run on 2026-09-27: `mdn_friday_cif_q22_g1_30f.h264`, split into
three 10-frame IDR-aligned segments; a 30-byte diagnostic payload was carried
as three 10-byte pieces. Embedding, full-stream strict decode, video-only
extraction, and exact payload comparison passed in **101.52 seconds**. This
does not embed an LNP22 proof and is not a capacity or realtime benchmark.
The same fixture's analysis reached **261.1 MiB RSS** from **37.1 MiB** before
analysis (**276.1 MiB peak working set**) and reported **180,966 raw safe
positions**; raw candidates are not stable/patchable carrier capacity. The
30-frame fixture cannot carry the full 33,803-byte compact probe proof.

The chunk transport is now listed as Phases 25-26 in `src/runtest/run_all.py`.
The full LNP22 video harness has **not yet been switched to this segmented
path**. Existing 3,000-frame Coastguard evidence only confirms 459,448
patchable bits for a different 57,415-byte proof target after scanning all 30
100-frame segments; it does not show successful multi-segment embedding,
proof extraction, or verification.
