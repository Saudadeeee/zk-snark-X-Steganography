# Ringo opening proof wire-format recheck (2026-09-30)

## Scope

Measured a complete serialized Buckler proof for the existing 32-byte payload
opening research circuit. The isolated `proof_codec.go` probe provides strict
JSON and schema-pinned binary codecs; neither is the application ZKP backend or
a production proof format.

## Revalidation (2026-10-01)

The focused proof and session-policy tests were rerun on commit `cbd934c`
using Go 1.26.2 (`windows/amd64`) on Windows 11 Pro, with a 12th Gen Intel
Core i7-12700H (14 cores / 20 logical processors) and 23.63 GiB visible RAM.
Command, from `benchmark/ringo_application_probe`:

```powershell
go test -run 'TestOpeningVerifierPolicy(ExpiryReplayAndStatementPinning|DoesNotSpendSessionOnInvalidProof)|TestOpeningRelationAndCapacityProbe' -count=1 -v
```

All three selected tests passed; Go reported 15.395 s package time. The
relation/capacity test took 9.53 s and measured compile 30.98 ms, prove
326.34 ms, and verify 143.97 ms in this single sample. The freshly serialized
proof measured 2,710,131-byte JSON, 1,653,727-byte binary, 1,281,714-byte
gzip JSON, and 1,246,230-byte gzip binary. The public commitment was 262,152
bytes; statement + commitment + proof + framing totaled 1,916,177 bytes
minimum, and the encoded fixed profile was 2,000,000 bytes. The process-local
policy tests passed for concurrent one-time use, expiration, unknown and
changed sessions, commitment pinning, and preserving the session after a
rejected proof.

After adding the statement-binding diagnostic below, `go vet ./...` and the
full `go test -count=1 ./...` both exited successfully; the full suite
reported 16.818 s. The default `go test -race -count=1 ./...` did not
complete: Go's checkptr aborted in
`github.com/sp301415/ringo-snark/math/crt.fwdNTTInPlacePow2Unroll` at
`math/crt/asm_ntt_amd64.go:112` with “converted pointer straddles multiple
allocations”. With `-gcflags=all=-d=checkptr=0`, the race-enabled suite passed
in 210.662 s without a race report. This workaround disables a memory-safety
check that found a dependency assembly issue; it is useful only as partial
race-detector evidence and does not make the default race/checkptr test pass
or clear the upstream finding.
Trying the dependency's `purego` build tag alone did not avoid the failure:
its scalar fallback also uses `unsafe` wide-array pointer casts and hit
checkptr in `math/crt/asm_ntt.go:92`.

### Confirmed Fiat-Shamir public-statement substitution (before local patch)

Source inspection of the pinned `ringo-snark` dependency found that Buckler's
prover and verifier bind proof commitments into the Fiat-Shamir transcript,
but do not bind the `PublicWitness` values. Those public values are only
evaluated later when the verifier checks arithmetic constraints. A dedicated
diagnostic circuit made this concrete: it enforces `Secret = 0` and
`Public = Secret`, so the all-zero public instance is true and every nonzero
public vector is false. The diagnostic test generated a valid all-zero proof,
recomputed its public `evalPoint` from the transcript, then replaced the public vector
with the cyclic NTT encoding of `X - evalPoint`. This polynomial is nonzero
coefficient-wise but evaluates to zero at that already-fixed point. Buckler's
low-level verifier accepted the false instance. The exploit diagnostic
reproduced in **10/10** randomized runs:

```powershell
go test -run '^TestDiagnosticStatementSubstitutionAfterFiatShamir$' -count=10 -v
```

This proves an adaptive public-statement substitution flaw for this generic
Buckler proof path. It is not, by itself, evidence that a deployed video API
has been remotely exploited. `openingVerifierPolicy.VerifyAndConsume` checks
the exact registered statement bytes and commitment digest before invoking
the low-level proof verifier, which blocks this substitution when those
values were independently and trustworthily pinned before proof construction.
The probe has no trusted enrollment/session-issuance API; its `Register`
method is an in-process policy primitive. Therefore the required trust
precondition is not established for the intended system, and this backend
must not be treated as a secure application ZK verifier. A fix requires a
formally reviewed binding of the canonical public instance and protocol
context into the Fiat-Shamir transcript (or another equivalently proven
construction), followed by rerunning this adaptive false-statement test and
the existing positive/negative cases. The working-tree remediation and its
post-patch evidence are recorded below; the original reproduction above is
retained as the pre-patch baseline.

### Reproduction on the application's opening circuit

Before the local transcript patch, the finding was additionally reproduced
on `openingCircuit` itself, not just the minimal diagnostic circuit. The test compiles the actual 32-byte opening
relation at rank 256, produces a valid opening proof, reconstructs its
Fiat-Shamir `evalPoint`, and adds the cyclic-NTT encoding of
`X - evalPoint` to one public commitment row. That is a nonzero change to the
public commitment vector; the secret and proof are unchanged. The low-level
application verifier nevertheless accepts it because the encoded difference
evaluates to zero at the challenge chosen before the public statement was
altered. This directly demonstrates proof-to-statement substitution in the
application relation. It does not by itself prove that the altered commitment
has no other valid opening under this research commitment relation; that
requires a separate binding argument. The generic diagnostic circuit above
does demonstrate acceptance of a mathematically false statement. In either
case, the current low-level integration does not bind the proof to the exact
public instance, so it cannot be accepted as the system's standalone verifier.

The pre-patch diagnostic was run 10 consecutive times and passed every time:

```powershell
go test -run '^TestOpeningDiagnosticStatementSubstitutionAfterFiatShamir$' -count=10
```

The session wrapper also rejected a substituted commitment when its exact
canonical commitment digest was independently registered before verification.
However, `Register` is an in-process policy primitive, with no authenticated
issuance endpoint or durable verifier-owned enrollment store. Therefore that
is defense in depth, not a system-level fix. The pre-patch test source is
[`opening_statement_substitution_diagnostic_test.go`](../ringo_application_probe/opening_statement_substitution_diagnostic_test.go).

### Local transcript-binding remediation and verification

The probe now vendors `ringo-snark` at `306742714785` and patches the Buckler
prover and verifier to bind the complete encoded public-witness vector before
the first Fiat-Shamir challenge. The canonical encoding is framed by a
domain tag, witness count, vector index, rank, and encoded byte length; the
existing encoded
polynomial bytes are then absorbed under `projConst`. Both sides call the
same helper, `buckler.bindPublicWitnesses`, before absorbing private
commitments. This is intended to make all downstream challenges depend on
the exact public instance, including the opening commitment and the
verifier-derived matrix, message, and mask vectors.
The JSON protocol, binary proof magic, and fixed transport magic were bumped
to v2 (`zkstego-ringo-opening-probe-v2`, `RZK2`, `RZV2`); tests explicitly
reject a v1 proof and envelope rather than silently mixing transcript rules.

The two tests now require the original valid proof to verify and the attack
crafted for the legacy transcript (with public witnesses omitted) to fail:
one uses a mathematically false minimal circuit, and the other mutates the
actual opening commitment vector. The
actual-circuit test also confirms the process-local session pin rejects the
same altered envelope. After the patch, both tests passed **10/10** runs:

```powershell
go test -run 'TestRejectStatementSubstitutionAfterFiatShamir|TestOpeningRejectsStatementSubstitutionAfterFiatShamir' -count=10 -v
```

The complete nested Go module suite passed (`go test -count=1 ./...`,
19.923 s on the latest run, including explicit v1-envelope rejection), and
`go vet ./...` passed. This verifies the
targeted regression and current probe tests only; it is not an independent
cryptographic review.
The pinned dependency remains research software, the default race/checkptr
failure described above remains, and the session registry is still
in-memory. H.264 embedding/extraction, API/CLI E2E, broad video benchmarks,
and independent analysis of proof soundness, zero knowledge, and commitment
binding are still required. Do not infer that the end-to-end objective is
complete or that this local patch is production-certified.

Primary-source references for this gate are the [pinned Buckler prover](https://github.com/sp301415/ringo-snark/blob/306742714785/buckler/prover.go),
[pinned verifier](https://github.com/sp301415/ringo-snark/blob/306742714785/buckler/verifier.go),
[Buckler PIOP paper, ePrint 2024/1879](https://eprint.iacr.org/2024/1879), and
[Jindo PCS paper, ePrint 2026/044](https://eprint.iacr.org/2026/044). The
papers' security analyses do not remove the need for the implementation's
Fiat-Shamir transcript to bind the public instance used by this application.

This was a targeted correctness revalidation, not a full-module test suite or
a repeated performance benchmark. The earlier capacity comparison is still
only a raw upper-bound estimate and no embedding/extraction was attempted.
The actual session registry remains in-memory and is not a deployed API.

Command, from `benchmark/ringo_application_probe`:

```powershell
go test -run '^TestOpeningRelationAndCapacityProbe$' -count=1 -v .
```

## Observed run

- Compile: 26.46 ms
- Prove: 300.89 ms
- Verify: 126.79 ms
- JSON encode: 65.21 ms
- JSON decode: 145.78 ms
- Binary encode: 46.21 ms
- Binary decode: 100.02 ms
- Verify after decoding the serialized proof: accepted
- Complete JSON proof: **2,710,137 bytes**
- Gzip JSON at `BestCompression`: **1,281,918 bytes**
- Schema-pinned binary proof: **1,653,727 bytes**
- `JindoParams.Size()/8` estimate printed by the probe: **550,249 bytes**
- JSON / estimate: **4.92x**
- Binary / estimate: **3.00x**
- Test process reported 5.01 s for the test and 6.33 s package time.

This is one local run. The proof is randomized, so its JSON length changes
slightly between runs; preceding runs produced 2,710,348, 2,710,642,
2,710,535, 2,710,571, and 2,710,141 bytes. The gzip measurement comes from the
last proof sample; it reduced that JSON by about 52.7%. Binary field encoding
is about 64.7% of JSON size and 29.0% larger than gzip in this run. Both
compressed representations remain far above the 10,779-byte carrier budget.
The ratio is approximately 4.9x for JSON and 3.0x for binary versus the
Jindo estimate. The codecs reject empty,
truncated, whitespace-altered, extra-value, empty-proof and otherwise
non-canonical JSON encodings. The application verifier wrapper also converts
dependency panics on malformed proof shapes into rejection errors.
The existing circuit controls also rejected changed context, changed public
commitment, non-Boolean bits, nonzero payload tail, and randomness outside the
configured bound.

### Additional proof-field and binary-compression sample

A later single local sample logged the binary proof by top-level structure:

| Proof component | Bytes | Share of complete binary proof |
|---|---:|---:|
| Buckler witness commitments (13) | 639,289 | 38.7% |
| Linear-check mask sum | 17 | <0.1% |
| Sum-check mask sum (nil marker) | 1 | <0.1% |
| Evaluation challenges | 222 | <0.1% |
| Jindo evaluation proof | 1,014,194 | 61.3% |

Within the evaluation proof, `Encode` is 557,295 bytes, `InCommit` 196,693,
`MLWE` 114,738, `Partial` 65,565, `MaskCom` 49,174, `SplitEvals` 28,328,
`MaskSplitEval` 2,178, and `BlindEvals` 222 bytes. This identifies the proof
commitments/evaluation vectors—not JSON field names—as the dominant wire cost.
Gzip BestCompression of the binary proof measured 1,246,440 bytes, versus
1,281,899 bytes for gzip JSON in that run; compression therefore saved only
about 24.6% over the uncompressed binary form. Even compressed, it is about
2.30x the 541,570-byte raw-capacity upper bound for the 3,000-frame cover, so
compression does not make this proof fit that tested clip.

The probe also logged the actual Jindo CRT moduli: two 42-bit inner moduli and
two 38-bit outer moduli. The generic experimental binary codec stores each
CRT residue in a 64-bit slot, so modulus-aware bit packing is a plausible
future optimization. Even the deliberately optimistic calculation that
shrinks every byte of the 1,653,727-byte proof by `42/64` yields about 1.09 MB,
roughly twice the clip's raw-capacity bound before metadata, framing,
patchability or visual-quality losses. This is only a feasibility estimate;
no such packed codec was implemented or measured. It rules out expecting
ordinary coefficient bit packing alone to close this clip's capacity gap.

The field sizes and compression result are one additional local sample, logged
by `go test -run '^TestOpeningRelationAndCapacityProbe$' -count=1 -v .`; they
are diagnostic measurements, not a repeated-run benchmark distribution.

### Rank sweep

The 32-byte payload circuit was parameterized for a one-run sweep at ranks
256, 512, 1,024, 2,048 and 4,096. Rank 256 is the minimum ring rank that
contains the exact 256 payload bits, with no zero-tail region. Every row below
generated a real proof, encoded and decoded it, and accepted that decoded
proof with the matching verifier. The 8,192 baseline is the separate full
probe run above; sample timing varies.

| Ring rank | Compile | Prove | Verify decoded proof | Binary proof | Gzip binary | Jindo estimate |
|---:|---:|---:|---:|---:|---:|---:|
| 256 | 6.30 ms | 36.11 ms | 13.63 ms | 998,087 B | 706,510 B | 262,729 B |
| 512 | 5.08 ms | 38.49 ms | 16.75 ms | 1,063,651 B | 766,022 B | 286,833 B |
| 1,024 | 8.18 ms | 80.01 ms | 25.52 ms | 1,129,215 B | 822,202 B | 325,813 B |
| 2,048 | 10.35 ms | 119.03 ms | 39.29 ms | 1,260,343 B | 926,794 B | 375,853 B |
| 4,096 | 14.29 ms | 170.89 ms | 69.51 ms | 1,391,471 B | 1,034,096 B | 447,895 B |

The minimum-rank proof alone still serializes to 998 KB (707 KB with gzip),
1.84x/1.30x the Coastguard 541,570-byte raw upper bound. It does not fit the
measured carrier, before public inputs, framing or patchability/quality loss. Its binary
serialization is 3.80x the Jindo estimate; `Size()/8` must not be used as a
substitute for complete proof serialization. Lower rank alone does not close
the measured clip's capacity gap. The sweep does not establish that rank 256
or any other tested rank has adequate lattice security; no such security claim
or production parameter recommendation is made. This is one local run per
rank, not a performance distribution, and no video embedding was attempted.

### Canonical verifier-context plumbing

The probe now takes a fixed-width `RGOS` v1 public statement as its matrix
derivation context. It is 282 bytes and encodes, in a fixed order, relation and
parameter IDs, registry root/epoch, session challenge, codec and carrier
profile IDs, exact 32-byte payload length, carrier count, positions hash, and
normalized-video commitment. The parser rejects wrong magic, truncation,
trailing bytes, unsupported versions, zero trust/context digests, a wrong
payload length, a zero epoch, and a non-byte-aligned carrier count.

The proof test uses fixture digests (not hashes computed from an actual H.264
video) and confirms that the same proof/public commitment is rejected after
changing the session challenge, normalized-video commitment, carrier-position
hash, codec policy, registry epoch, or carrier count. Statement round-trip and
canonical-length tests passed. This verifies plumbing inside the experimental
Ringo relation only: the code does not resolve IDs against a trusted registry,
derive these hashes from a received H.264 stream, issue/expire challenges,
track spent challenges, or establish a proof security theorem.

### Complete fixed-profile in-band envelope

The proof is not the verifier's entire input: the public commitment and
statement must also be transported. The probe now serializes these in an
`RZV1` fixed-profile envelope: 16-byte header (magic plus three big-endian
lengths), 282-byte canonical statement, `RZC1` public commitment, binary proof,
then canonical zero padding to the verifier-pinned carrier count. At rank
8,192, the commitment is `8 + 2 * 8,192 * 16 = 262,152` bytes. Combining the
statement, commitment, proof and header yields a minimum envelope of
**1,916,177 bytes**. The test uses a pinned 16,000,000-bit / 2,000,000-byte
profile, encodes and decodes the complete envelope, then verifies the decoded
proof. The latest local sample measured envelope decode at 107.71 ms; it is a single
measurement and excludes H.264 blind extraction.

The fixed profile is **3.69x** the retained 541,570-byte raw-safe capacity for
the 3,000-frame Coastguard cover. The minimum non-padded envelope is 3.54x that
upper bound. Thus the fully counted verifier input does not fit this cover,
even before considering that raw-safe candidates are not necessarily patchable
or quality-safe. The earlier `1,653,743-byte / 3.05x` comparison was only the
binary proof plus 16 bytes of framing; it omitted the required 262,152-byte
public commitment and 282-byte statement and must not be interpreted as the
complete channel payload.

Malformed-envelope checks reject truncation, bad magic, forged field lengths,
nonzero padding, a changed session challenge and a changed public commitment.
This validates only the probe's fixed-profile codec. No Ringo proof was
embedded into or blindly extracted from H.264, and the fixture statement is
not resolved against a live verifier policy or replay/expiry service.

### Process-local session-policy probe

The fixture constructor was generalized to accept a caller-supplied 32-byte
payload and sample fresh private ternary opening randomness. A real test proved
and verified two different payload values under the same public context, and
observed different canonical commitment encodings; a wrong-length payload was
rejected. This removes the probe's hard-coded-message limitation, but the
commitment is still produced by this fixture, not enrolled by a trusted issuer
or derived from a deployed session registry.

`policy.go` adds a research-only verifier registry keyed by the 32-byte session
challenge. Registration pins the exact canonical `RGOS` statement bytes, the
expected canonical public commitment digest, and a server-supplied expiry in
memory. This commitment pin is required: checking only a statement would allow
a prover to supply a different commitment and a valid proof for another
payload under that same session. Verification peeks the bounded header,
statement and commitment first, rejects unknown/expired/mismatched sessions
before decoding the large proof, marks the challenge pending to serialize
concurrent attempts, then consumes it only if the decoded proof verifies and
the session is still unexpired. Invalid or unregistered-commitment proofs
release the pending state without spending the challenge.

`TestOpeningVerifierPolicyExpiryReplayAndStatementPinning` generated and
verified a real local Ringo proof: in a two-request concurrent replay, exactly
one was accepted; the expired session, unregistered session and changed video
statement were rejected. `TestOpeningVerifierPolicyDoesNotSpendSessionOnInvalidProof`
generated and independently verified a second valid proof for a different
private bit payload and commitment under the same statement. The session
policy rejected that alternate valid proof because its commitment was not the
verifier-registered target; the original valid proof could still use the
session. Targeted tests and race-enabled policy tests passed. This is volatile
single-process state, not persistent or distributed
replay protection. Session issuance is not an authenticated API, and the policy
is not connected to H.264 extraction or the application verifier.

### Additional real-video raw-capacity diagnostic

The existing 300-frame `data/encoded/coastguard_cif_q22_g1.h264` was scanned
with the repository's `benchmark.streaming_capacity_scan` implementation and
FFmpeg 8.0.1. The saved result is
`benchmark/results/ringo_raw_capacity_coastguard_300f_20260930.json`:

| Video | Frames | Raw-safe candidates | Scan time | Approx. scan rate | Quality validated | Blind extraction validated |
|---|---:|---:|---:|---:|---|---|
| Coastguard CIF QP22/GOP1 | 300 | 3,827,207 bits (478,401 B) | 1,212.161 s | 0.247 frame/s | No | No |

This is only an upper bound on raw CAVLC-safe positions. It does not measure
patchability, final image quality, extraction, or proof embedding. The current
minimum Ringo verifier envelope (1,916,177 B) is about **4.01x** this clip's
raw capacity; its 2,000,000-byte fixed profile is about **4.18x**. The measured
raw capacity is notably content/profile-specific and must not be extrapolated
from the earlier 3,000-frame Coastguard file.

The scanner's JSON `proof_bytes`/`fits` fields refer to the older 131,694-byte
LNP22 diagnostic file passed to the legacy scanner CLI; they do **not** assess
the Ringo envelope. Use `raw_safe_carrier_bits` for the candidate count and the
1,916,177-byte calculation above for the Ringo comparison. An explicit
allowlist was added because benchmark JSON is ignored by default.

A fresh raw scan of `coastguard_cif_q22_g1_3000f.h264` with the same current
command was started to compare against its retained 2026-09-27 raw scan. It
was stopped after 30 minutes because it remained CPU-active without producing
the final report. Therefore there is no new comparable 3,000-frame result;
the old 4,332,560-bit/541,570-byte artifact remains historical evidence only.
This 30-minute non-completion is an offline scanner runtime observation, not a
completed benchmark result and not proof that the 3,000-frame scan would never
finish.

### Capacity-scanner hotspot diagnostic (2026-09-30)

A 10-frame stream-copy excerpt from the same CIF QP22/GOP1 input was scanned
with the updated scanner. It yielded 126,628 raw-safe candidates in 39.013 s
(0.256 frame/s). The supplied legacy LNP22 artifact was 131,694 bytes, so the
scanner's raw-only comparison required 1,053,680 bits including its 16-byte
framing and did not fit. Quality, patchability and blind extraction were not
measured. This short excerpt is a smoke diagnostic, not a replacement for the
300-frame scan or a representative throughput benchmark.

An instrumented `cProfile` run of that same scan recorded 78,892,819 calls in
104.434 s (the instrumentation materially increases elapsed time). The
dominant cumulative paths were `CAVLCSafetyFilter.get_safe_positions`
(79.924 s), `_verify_block_bit_length_invariance` (66.077 s), CAVLC forward
decode (55.107 s) and CAVLC encode (31.989 s). These overlapping cumulative
times are not additive. Extracting just the 10-frame block vectors found
61,794 distinct coefficient/context keys among 62,592 blocks: 798 repeated
blocks (1.27%). Therefore a cross-block verification cache was not added; on
this sample it would have little reuse and would add memory/key-management
complexity. The measured 0.256 frame/s is close to the prior 300-frame
0.247 frame/s, so this diagnostic does not demonstrate a throughput gain from
the scanner-order optimization or source-length cache correction.

### Blind-stable capacity scan (2026-09-30)

The scanner now has an explicit `--stable-blind-carriers` profile and accepts
`--target-payload-bytes`, so capacity can be compared against the full Ringo
envelope size without passing an unrelated file as if it were a proof. On the
same 300-frame Coastguard CIF QP22/GOP1 input, scanning only deterministic
blind-stable carriers yielded **76,550 raw-safe bits** (9,568 bytes) in
**439.958 s** (0.682 frame/s). The report is
`ringo_blind_stable_capacity_coastguard_300f_20260930.json` and targets the
minimum 1,916,177-byte Ringo envelope plus 16-byte framing (**15,329,544
bits**). That target is about **200.3x** this scan's raw blind-stable upper
bound. On this identical clip, the all-safe-candidate scan reported
3,827,207 bits, about 50.0x the blind-stable count; those extra positions
cannot be assumed available to a verifier that re-derives one deterministic
carrier per block.

The blind-stable measurement is still not proof embedding: quality validation,
actual patchability, and end-to-end blind extraction remain false/not measured.
The 0.682 frame/s scan rate is offline analysis throughput, not camera pipeline
latency or a realtime claim. It is content/profile-specific and cannot be
extrapolated to other resolutions or clips.

A second 300-frame CIF QP22/GOP1 asset, `akiyo_cif_q22_g1.h264`, was measured
with the same stable-carrier command and 100-frame segment size. It yielded
**20,632 raw-safe blind-stable bits** (2,579 bytes) in **198.021 s**
(1.515 frame/s), versus Coastguard's 76,550 bits in 439.958 s (0.682
frame/s). The Akiyo count is 3.71x below Coastguard despite equal frame count,
resolution, QP and GOP, demonstrating that this raw carrier estimate depends
strongly on content. Akiyo's minimum-envelope target is short by 15,308,912
bits; the 15,329,544-bit requirement is **743.0x** its raw-stable capacity.
The machine-readable Akiyo result is
`ringo_blind_stable_capacity_akiyo_300f_20260930.json`.

Both rows are raw candidate scans only. Neither establishes patchability,
blind extraction, final visual quality, or end-to-end latency/RAM. The scan
rates are offline analysis throughput and are not realtime camera performance.

### Rank-stable fallback selector recheck

The stable carrier selector now falls back past an individually unsafe
structural candidate only when all earlier candidates remain unsafe after
hypothetically toggling the selected coefficient. This symmetric check
prevents the verifier from selecting a different earlier position after
embedding. An actual 10-frame Akiyo H.264 embed/extract run carried the
ordinary 8-byte value `4c6174746963655a` using 176 framed carriers. Blind
extraction recovered the exact value; cover and stego independently derived
identical carrier lists and candidate fingerprints, and their
carrier-normalized digests matched. The embed API's strict FFmpeg decode
validation also completed successfully. This was not a ZK proof test, and the
output was temporary; no wall-time or RAM measurement was retained.

After this selector change, `py -3.12 -m pytest -q
src/runtest/test_video_only_blind_sync_integration.py` completed with **3
passed in 376.96 s**. This suite includes the Foreman 300-frame real-video
embed/extract, independent position derivation, fast/direct extraction
agreement, context-binding checks, and truncation rejection. The reported
pytest wall time is a single integration-suite observation (not a per-frame
latency or RAM benchmark), and the payload is ordinary test data rather than
a lattice proof. It must not be interpreted as realtime performance.

The selector was then scanned over the same 300-frame Akiyo CIF QP22/GOP1
asset as the preceding result. Raw blind-stable candidates increased from
20,632 to **29,847 bits** (+44.7%) in **225.634 s** (1.329 frame/s), compared
with 198.021 s for the first-structural-candidate selector. The new report is
`ringo_blind_stable_capacity_akiyo_300f_fallback_20260930.json`; its video
hash matches the preceding Akiyo scan. This is still raw capacity only: no
complete patchability target, proof embedding, blind proof extraction,
image-quality measurement, or RAM measurement was performed. The Ringo
envelope plus framing still needs 15,329,544 bits, **513.6x** this improved
raw upper bound.

### Multi-carrier-per-block screening (10-frame Akiyo excerpt)

To assess whether the one-carrier-per-block stable profile is an avoidable
capacity limit, a 10-frame Akiyo stream-copy excerpt was parsed and every
structurally stable luma coefficient (non-DC, not a trailing one, magnitude at
least four) was individually checked with the repository's CAVLC encoder
against its source NAL block length. This found 1,732 individually invariant
positions across 1,039 eligible blocks in 33,074 parsed luma blocks. The
candidate-count histogram was: 611 blocks with one, 268 with two, 92 with
three, 39 with four, 21 with five, and 8 with six eligible positions; the
remaining 32,035 blocks had none.

Individual invariance does not imply joint invariance. Applying the first `k`
individually safe coefficient flips together and re-encoding each original
block produced:

| Prefix size `k` | Blocks tested | Jointly bit-length invariant | Rate |
|---:|---:|---:|---:|
| 1 | 1,039 | 1,039 | 100.0% |
| 2 | 428 | 402 | 93.9% |
| 3 | 160 | 157 | 98.1% |
| 4 | 68 | 62 | 91.2% |
| 5 | 29 | 25 | 86.2% |
| 6 | 8 | 6 | 75.0% |

These are screening counts, not additional carrier capacity claims: the run
did not call the bitstream patcher, write a multi-carrier stego video, extract
payload, decode the result with FFmpeg, or measure visual quality. In
particular, an implementation must make the chosen group re-derivable from
the stego coefficients and verify joint (not just per-coefficient)
patchability. The 6.1% pair failure rate is direct evidence that simply
removing the current one-modification-per-block guard would be unsafe.

## Interpretation and limits

The earlier 550,249-byte figure was an estimate, not an encoded proof size.
The uncompressed JSON artifact is about 251 times and the schema-pinned binary
artifact about 153 times the 10,779-byte carrier budget reported for the
earlier Coastguard transport; gzip was about 119 times that budget. None of
these representations fits that carrier. This says nothing universal about
longer or higher-capacity videos.

There is also a raw-capacity upper bound from the retained 3,000-frame
`coastguard_cif_q22_g1_3000f.h264` scan:
`benchmark/results/streaming_raw_capacity_coastguard_3000f_20260927.json`
records 4,332,560 raw-safe bits, or 541,570 bytes, before patchability,
blind-extraction and quality losses. The proof-only binary size plus 16-byte
framing is 1,653,743 bytes (3.05x the raw upper bound); that earlier estimate
omitted the public commitment and statement. The actual minimum complete
envelope is 1,916,177 bytes (3.54x), or 2,000,000 bytes (3.69x) for the pinned
fixed profile. Thus this exact 3,000-frame cover cannot carry the complete
current Ringo verifier input even if every raw-safe coefficient were
patchable. This is an upper-bound comparison; no H.264 Ringo embedding was
performed.

No video embedding/extraction was run with this proof. Memory and repeated-run
latency distributions were not measured. The relation, CRS, Ringo implementation
and parameters remain research-only; the proof codec and this test do not
establish independent cryptographic security review or production suitability.
