# Current ZKP path revalidation (2026-09-29)

## Result

The current public video API still has no active lattice-ZKP backend. The
default lattice path is ML-DSA attestation with a sidecar reference; the
experimental SIS proof path remains disabled. The statement-contract helper
tests pass, but they do not prove or verify an application relation.

## Current-source evidence

- `src/embedder.py:407-408` rejects `proof_backend="lattice_zkp"` before
  processing the video. For the default `lattice` path, lines 467-474 serialize
  a Groth16 proof for the legacy backend, or create an `LatticeReceipt` and
  store only its commitment in the video payload. The receipt sidecar is saved
  at line 759.
- `src/verifier.py:180-181` likewise rejects `lattice_zkp`; the default
  `lattice` path verifies the ML-DSA receipt against the message and public key
  (`src/verifier.py:325`). The blind verifier also rejects a manifest selecting
  the research-only SIS artifact before parsing H.264
  (`src/verifier_blind.py:114`).
- `src/video_zkp_contract.py:50-58` computes an experimental SHA3 commitment
  from a private opening and payload. `build_video_zkp_statement()` builds a
  canonical helper statement, and its video-commitment helper still accepts
  carrier positions from the caller. These helpers do not invoke a proof
  backend or constitute proof verification.
- `src/runtest/test_lattice_zkp.py` intentionally characterizes that the SIS
  prototype allows a prover-selected statement and verifies that the public
  embed/verify APIs reject the unreviewed backend.

## Fresh test execution

Ran on the current worktree on 2026-09-29:

```text
py -3.12 -m pytest -q src/runtest/test_lattice_zkp.py src/runtest/test_video_zkp_contract.py src/runtest/test_lnp22_video_e2e.py
30 passed in 2.32s

py -3.12 -m src.lazer_backend
{"blockers":["avx512f_required"],"docker_available":true,"machine":"x86_64","ready":false,"system_name":"Linux"}
```

The 30 tests cover fail-closed/prototype characterization, canonical statement
and registry-helper behavior, and the LNP22 HTTP/envelope/video-E2E *test
harness*. The LNP22 E2E tests stub proof/extraction dependencies in the cases
that exercise the harness; this run did not execute an accepted lattice proof
backend, did not embed a proof into a produced H.264 video, and did not prove
the payload-commitment opening. The LaZer Toolkit candidate cannot even be
smoke-tested on this host because AVX-512F is absent. Docker availability does
not remove this CPU-feature gate because the container shares the host CPU.

Interpretation: these are useful regression checks for explicit rejection and
statement plumbing, not evidence that the target system works end-to-end. The
application-relation, proof serialization, in-band capacity/quality, blind
extraction and independent verification acceptance gates remain open. The next
valid integration gate is an independently reviewable backend/relation pair;
obtaining an AVX-512 runner alone would only permit testing the Toolkit example,
not make that example prove this application's statement.

## Fresh prototype artifact-size check

On this Windows host, using the isolated Python 3.12 environment, generated and
verified one `LatticeZkProof` for the sample message `video-payload-demo` and
32-byte witness key `0x4b` repeated 32 times. The actual JSON serialization
(`json.dumps(to_dict(), sort_keys=True, separators=(",", ":"))`) measured
**131,692 bytes (128.61 KiB)**. The encoded fields were 344 characters for the
statement, 43,692 for commitments and 87,384 for responses. This run took
0.1735 s to prove and 0.1439 s to verify; it is one diagnostic run, not a
performance benchmark. Verification returned `true`.

This artifact proves only the prototype's prover-selected bounded SIS
statement; it is not an application proof for payload opening, H.264 context,
carrier locations or codec execution. Its measured JSON size is the relevant
serialized artifact size before any in-band framing. No matching end-to-end
video carrier-capacity run was performed in this check, so this number alone
does not establish fit or non-fit for every video. It does establish that
proof-size feasibility must be tested against measured carrier capacity using
the exact serialized artifact, rather than inferred from the small witness or
the algebraic statement size.

## Future statement challenge-input correction

`embed()` previously used the ML-DSA receipt commitment as the future
statement's `session_id`, although the video-only context helper expects the
verifier-issued 32-byte challenge. It now accepts `zkp_session_id` and requires
it together with all other future-statement inputs; missing or malformed
challenges fail before relation-registry resolution or video parsing. The
statement builder uses this challenge instead of the receipt commitment.

Rechecks on the current worktree:

```text
py -3.12 -m src.runtest.test_lattice_zkp       9/9 passed
py -3.12 -m src.runtest.test_video_zkp_contract 9/9 passed
py -3.12 -m py_compile src/embedder.py src/runtest/test_lattice_zkp.py passed
```

This does not make the emitted future statement verifiable: it is still a
sidecar, the video embeds the ML-DSA receipt reference rather than a ZK proof,
and the active embed carrier selection is not the stable session-derived
carrier profile required by the video-only context helper. The caller must
also provide challenge freshness and one-use replay tracking. No ZK backend or
public verifier behavior changed.

## Fresh status recheck (2026-09-30)

Re-ran the current fail-closed and statement-contract test scripts:

```text
py -3.12 -u src/runtest/test_lattice_zkp.py        9/9 passed
py -3.12 -u src/runtest/test_video_zkp_contract.py 9/9 passed
py -3.12 -m src.lazer_backend
{"blockers":["docker_daemon_unavailable"],"cpu_flags":[],"docker_available":false,"machine":"","ready":false,"system_name":""}
```

The passing SIS test suite intentionally includes
`sis_prototype_accepts_a_prover_selected_statement`; that test characterizes a
security limitation of the research prototype. It is not evidence that the
prototype is an acceptable verifier. The same suite confirms the public video
APIs reject the unreviewed proof backend before parsing video, and the
separate statement-contract suite tests canonicalization and policy helpers
only; neither suite generates/verifies an accepted application ZK proof.

Independently queried this Windows host's CPU target using the installed
native GCC with `g++ -march=native -Q --help=target`: AES and AVX2 are enabled,
but AVX-512F is disabled. `docker info` also failed because the Docker Desktop
Linux engine pipe is absent. Therefore bringing Docker back up would not clear
the pinned LaZer CPU-feature gate on this host. This leaves the same concrete
backend gap: the current API is fail-closed, LaZer cannot run here, and LUNA's
available repository is only an HGSW primitive implementation.

## Trailing-one carrier/policy consistency recheck (2026-09-30)

The video-only statement path labels its carrier strategy `t1_sign_flip`, but
its prior integration fixture used the magnitude-LSB stable profile. The
verifier did not reject that mismatch, and the sign-bit-only carrier branch
selected zero positions because it intersected trailing-one sign positions
with the separate magnitude-LSB candidate set. A RED test reproduced both
problems; the first real-video attempt failed with `need 176 carriers, got 0`.

The current branch now requires `signbit_only=True` for a video-only statement
whose pinned policy is `t1_sign_flip`. Sign-bit candidate derivation and its
fingerprint use the negative-index trailing-one carriers returned by the
CAVLC safety analysis; magnitude-LSB candidates are no longer substituted.
Metadata reports `full-v1` for the full safety-analysis mode used to derive
these signs. The metadata schema remains `blind-sync-stable-v1` when an
explicit stable candidate override is used, so changing only the descriptive
analysis label does not silently change the metadata-bound ordering seed. A
regression test covers this with `metadata_bound=True`.
The carrier-policy descriptor now also includes the metadata schema version,
so registries/policies minted before that binding change fail closed and must
be registered again; old and new metadata-bound ordering cannot share one
policy digest silently.

The corrected real-video integration test passed on
`data/encoded/foreman_cif_g8_300f_b800k.h264` (352x288, 20 fps, 300 frames;
SHA-256 `db25d6ce01f31f840466f88a2a864b0c27402616298b7105b0dce28ad3c58e9e`).
It carried an ordinary 8-byte test payload in a 14-byte envelope header plus
payload (22 bytes / 176 bits). The test verified exact blind extraction,
matching cover/stego carrier positions and fingerprints, canonical normalized
video digest equality, and strict FFmpeg decode validation. It completed in
**497.94 seconds**. At the input's nominal 20 fps, 300 frames represent about
15 seconds, so this whole test duration is roughly **33.2x the clip duration**.

This is a single payload-channel integration test, not a proof test or formal
performance benchmark. It does not generate or verify a lattice-ZK proof and
does not measure isolated CPU/RAM, PSNR/SSIM, or a repeated-run distribution.
It is clear evidence that the current Python video-only sign-bit channel is
not realtime on this host, even for a 176-bit diagnostic payload. The active
application ZK backend remains unavailable/fail-closed as stated above.

## Proof-wire capacity gate from existing measurements

The separate Ringo application-opening probe measured its smallest tested
rank-256 proof at 998,087 bytes binary (706,510 bytes with gzip). The
3,000-frame Coastguard diagnostic reported only 541,570 bytes of raw carrier
capacity before framing, patchability, or visual-quality losses. Thus even
the compressed rank-256 artifact is about 1.30x that optimistic upper bound;
the binary artifact is about 1.84x. This cross-check is a feasibility
comparison of existing measurements, not an embedding run, and rank 256 has
no established security parameterization. It indicates that the tested Ringo
opening-proof wire format does not fit that cover under the measured raw
capacity, so it cannot presently satisfy the no-sidecar requirement there.

The smaller 131,694-byte SIS artifact recorded elsewhere is not a substitute:
it proves a prover-selected research statement, not the required application
relation. The sign-bit-only profile has not yet had a full-capacity/patchability
measurement, so no capacity claim for that profile is made here.

## Sign-bit capacity and real payload-channel sample (2026-09-30)

`benchmark/streaming_capacity_scan.py` now has an explicit
`--signbit-carriers` mode that follows the verifier's negative-index trailing-
one sign selection and counts at most one candidate per block. It deliberately
reports only a raw CAVLC-safe upper bound: sign-bit targeted patchability and
per-frame quality are not claimed by this scanner.

Ten-frame GOP-1 samples from the existing 352x288 QP22 H.264 Constrained
Baseline inputs (25 fps average) produced:

| Clip | Raw sign-bit carriers | Scan time | Raw-fit ratio for 1,916,177-byte verifier envelope |
|---|---:|---:|---:|
| Coastguard | 55,420 bits | 41.746 s | 276.6x short |
| Akiyo | 30,360 bits | 13.653 s | 504.9x short |
| Foreman | 2,154 bits | 4.584 s | 7,116.8x short |

The inputs were the first 10 frames copied from
`coastguard_cif_q22_g1.h264`, `akiyo_cif_q22_g1.h264`, and
`foreman_cif_q22_g1.h264` respectively. The resulting scan-clip SHA-256 values
were `fc86406b8dab0ad54f720712d5ebc365009e285e72a140d07c0e5e39de32e084`,
`3c13b406c8933f522b2903e4b01c9e90daa90cfe25cba94d82a8e8fd20b8c3fd`, and
`83e8e402bedd21a5613bf0c4ff03e2e6be2c5784ddc962915300a55195cc5bb9`.
These are per-clip ten-frame observations, not extrapolations to longer videos;
the count varies sharply by content. They do not validate a full proof fit,
because patchability, blind extraction at this capacity, and quality were not
measured for every row.

A separate actual embed/extract run used the Coastguard ten-frame clip and a
4,096-byte deterministic diagnostic payload (not a proof). The envelope was
4,110 bytes; the pipeline used 32,880 sign-bit carriers, modified 16,470
coefficients, produced an H.264 file with the same 331,482-byte size, and
blindly extracted the exact payload. Strict FFmpeg decoding passed inside the
embed routine. Embed plus blind extraction took **192.952 s** for a 10-frame,
25-fps clip (0.4 s duration), around **482x slower than the clip duration**.
The stego file SHA-256 was
`22a104b822cbb5b7cf604dd5e1cbb0e3e3921d8ff07dab2a3daab3f7a6baadc1`. This is
not realtime.

FFmpeg per-frame comparison of decoded cover/stego samples yielded luma PSNR
mean **30.862 dB** (min 28.46, max 32.21) and SSIM-All mean **0.977978** (min
0.976048, max 0.980206); Cb/Cr were unchanged in this sample. This is one
short run, not a repeated quality/performance benchmark, and the luma changes
are not negligible. Peak RAM was not captured. The result validates a larger
diagnostic payload channel only; it does not generate, embed, or verify a
lattice-ZK proof.

## Native CAVLC transport matrix and proof-size stress gate (2026-09-30)

The native x264-fork matrix ran 24 combinations: eight source sequences and
three resolutions (176x144, 352x288, 704x576), with 260--1,374 frames per
sequence. Every successful case carried only the 15-byte `ZKVP` envelope for
one diagnostic byte (120 bits), then passed blind byte extraction. This is
transport validation, not a proof run. Across the matrix, encode throughput
was 31.666--611.533 fps, sampled encoder peak RSS was 5.578--11.203 MiB, and
the Python batch extractor took 0.989--14.271 s with 37.445--64.273 MiB peak
RSS. Per-frame PSNR versus the original Y4M ranged 35.287--52.373 dB and
corrected FFmpeg all-plane SSIM ranged 0.919812--0.998721. These quality
numbers include lossy CRF encoding; there was no matched no-payload encode to
isolate distortion from embedding. The slowest 704x576 extraction was a
whole-video operation, so native encoder throughput alone does not establish
realtime verification.

A native capacity stress run used a 33,803-byte experimental LNP22 artifact
(SHA-256 and run details are in
`benchmark/results/native_payload_capacity_probe_20260930.md`). It is not a
valid proof of the target relation. On 300-frame 352x288 Akiyo, the encoder
committed 10,420 of 270,424 requested bits (3.85%), forced all 300 frames to
IDR/I pictures while trying, then rejected publication and removed the partial
output. Wall time was 3.029 s; peak RAM was not measured reliably. This gives
a real failure boundary for that artifact and encoder profile, not a universal
capacity bound. It also exposes a coding-efficiency cost of the current
IDR-only carrier strategy. The native multi-resolution transport matrix and
this stress run still do not embed an accepted application proof; the public
lattice-ZK API remains fail-closed.

An opt-in P-slice capacity probe was then run on the same 300-frame Akiyo
sequence. A 33,803-byte artifact committed 4,870 of 270,424 bits before the
adapter rejected publication; no partial video was kept. A 300-byte prefix
payload completed with 2,400 payload bits embedded, produced a 705,370-byte
Constrained Baseline stream, and FFprobe counted all 300 frames. FFmpeg decoded
the output without errors. However, the blind extractor rejected the P-slice
stream because its CAVLC parser reported a heuristic resynchronization error
inside a P slice (`mb=121`, impossible `intra_chroma_pred_mode` after parsing
earlier P macroblocks). As a control, a standard FFmpeg/libx264 Baseline
CAVLC encode of the same source also failed the parser's strict P-slice
integrity gate in 7 of its first 10 P slices (only 3/10 parsed without
integrity issues). This isolates a pre-existing verifier/parser limitation,
not evidence that the embedded video is malformed. P-slice byte embedding is
therefore not yet end-to-end usable: the verifier must first parse and extract
from general P-slice syntax reliably. These payload probes are not ZK proofs.

A follow-up encoder run disabled intra analysis in the opt-in mode; x264 then
reported only P16x16/skip macroblocks in P pictures (I pictures were I16x16).
The same 300-byte payload encoded and decoded as a 300-frame Baseline stream,
but blind parsing still desynchronized on the second P slice at macroblock 151
(`mb_type=219`, outside the valid P-slice range). This narrows the remaining
parser failure beyond P-intra syntax: P-inter prediction/residual parsing or
coefficient-context tracking is still misaligned. The extractor correctly
fails closed and does not return bytes from this stream.

## P-slice parser repair and blind transport recheck (2026-10-01)

The parser desynchronization above was traced to skipped macroblocks: the
parser recorded their zero-valued blocks in the output map, but did not record
their `TotalCoeff=0` values in the neighbor cache used for CAVLC `nC`
prediction. A skipped macroblock is still an available neighbor. Omitting it
made later blocks use a one-neighbor context instead of averaging both
available neighbors, selecting the wrong `coeff_token` VLC and shifting the
rest of the slice. The parser now records all 24 luma/chroma block counts as
zero for each skipped macroblock. A regression test exercises a skipped left
neighbor plus a nonzero top neighbor and asserts `nC=3`.

Revalidation on real streams passed the strict parser integrity gate for all
9/9 P-slices of a 10-frame 176x144 FFmpeg `testsrc2` Baseline/CAVLC stream and
all 290/290 P-slices of both the earlier 300-frame native x264 P-carrier
stream and the standard 300-frame FFmpeg/libx264 Baseline control stream.
The latter reverses the previous 3/10 first-slice result after correcting
the skipped-neighbor cache.
For the latter, a 200-byte diagnostic payload was wrapped in the in-band
`ZKVP` envelope (214 bytes / 1,712 bits), embedded in P-slice residuals, and
blindly extracted byte-for-byte without a sidecar. The output was a 300-frame
352x288 Constrained Baseline H.264 stream (512,117 bytes); FFprobe counted all
frames and strict FFmpeg decode returned success. Stego SHA-256:
`4bbd2fc4e9e56bfe7e9e0ad3c6599fa374dbc960158d992f5033b32642bc1d3b`.
One blind extraction run took 21.337 s wall time; peak RAM was not measured.

This is a diagnostic payload transport result, not a lattice proof or proof
verification. Capacity remains content- and resolution-dependent: on the
same 352x288 upscaled Akiyo input, a 314-byte envelope (300-byte payload)
failed closed after the encoder found only 2,075 of 2,512 required carrier
bits. At 176x144 it found 1,122 bits. The successful 200-byte sample does not
establish a full-proof capacity bound, quality benchmark, or realtime claim.
