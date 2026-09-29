# Ringo opening proof wire-format recheck (2026-09-30)

## Scope

Measured a complete serialized Buckler proof for the existing 32-byte payload
opening research circuit. The isolated `proof_codec.go` probe provides strict
JSON and schema-pinned binary codecs; neither is the application ZKP backend or
a production proof format.

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
