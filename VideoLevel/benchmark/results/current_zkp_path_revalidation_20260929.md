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
