# Post-quantum video-ZKP completion plan

## Target claim

The eventual system shall prove, without revealing a payload or placement seed,
knowledge of a witness satisfying a **reviewed lattice relation** bound to:

```text
verifier_challenge || payload_commitment ||
carrier_normalized_video_digest || derived_carrier_set_digest ||
fixed_relation_id || pinned_registry_root || registry_epoch ||
canonical_codec_and_carrier_policy
```

The verifier derives the video digest and carrier set from the received H.264
bitstream; it does not trust prover-supplied `cover_hash`, positions, policy,
or relation selection. A cover hash is not a verifier-checkable claim in the
blind, video-only flow unless the verifier also possesses that cover.

It shall not claim that a proof verifies all H.264 encoder arithmetic unless a
separate, explicitly implemented codec relation is included. ML-DSA authenticates
the control plane; ML-KEM establishes transport secrets; neither is called a ZKP.

`src/video_zkp_contract.py` now canonicalizes this public statement. Payload
commitments are salted with a private 32-byte opening, and parsing always
recomputes the canonical statement ID. `src/zkp_registry.py` requires the
relation to resolve from an ML-DSA-65-signed, verifier-trust-anchored registry.
Each relation ID is derived from a descriptor of its constraint module,
verifier key, parameter set, and admissible policy; verifiers must fetch those
artifacts by their pinned hashes. The statement records the issuer-bound
registry payload's derived root and epoch. It is the single byte-level contract that a LaZer prover and
verifier must consume.

## Architecture (target requirement; not implemented)

```text
sender secret / registered public statement
          │ witness
          ▼
LaZer prover ── serialized proof ──► direct CAVLC carrier in H.264 video
                                          │
                                          ▼
                              blind extraction from video
                                          │
                                          ▼
                           registered relation + verifier

Optional sidecar: registry/issuer metadata and signature over final artifact.
It must not contain the only copy of the proof or be required to recover it.
```

The sidecar-proof design previously described here does **not** satisfy the
user requirement that the proof itself be embedded in the video. It is retained
only as a record of the current prototype, not as the target architecture. The
target must carry the complete serialized proof (plus enough framing/version
information to extract and verify it) in CAVLC-residual carriers, without SEI.
An identifier or hash pointing to proof bytes in a sidecar does not pass.

There is a circular-binding issue to solve before implementation: proof bytes
change the stego bitstream, so a proof cannot naively contain the hash of the
final file that contains that proof. Specify and review a canonical video
commitment that excludes or normalizes only explicitly identified proof-carrier
fields, and bind the carrier map, session, payload commitment and codec policy
into the statement. Any optional signature over the exact final file is a
separate outer integrity mechanism; it does not replace the ZK relation.

### Candidate video-only protocol v3 (design clarification; not implemented or reviewed)

The in-tree `VideoZkpStatement` v2 is only a contract scaffold. It has both a
`cover_hash` and a `stego_hash`, accepts an externally supplied position list
for canonicalization, and is not itself a proof verifier. It must not be
mistaken for the final blind protocol. The following is the single proposed
direction to review before changing that schema or the proof envelope.

**Verifier-derived public instance.** Let the verifier have an outstanding,
single-use 32-byte challenge `N`, a locally pinned relation descriptor `R`,
registry snapshot `(root, epoch)`, and a fixed codec/carrier policy `P`. Parse
the received bitstream under Baseline/CAVLC only. Derive the complete ordered
candidate carrier set `C = CarrierSet(video, P)` by a deterministic traversal
of eligible residual coefficients. The policy must make candidate eligibility
invariant under every legal embedded symbol (for example, modifications may
not create/remove a nonzero coefficient); reject the stream if that invariant
cannot be established. The verifier derives:

```text
V = SHA-256("zkstego/video-canonical/v3\0" || Canonicalize(video, C, P))
J = SHA-256("zkstego/carriers/v3\0" || EncodePositions(C))
S = EncodeCanonical(v3, N, payload_commitment, V, J, R, root, epoch, P)
```

`Canonicalize` must preserve all non-carrier NAL/RBSP syntax and replace every
candidate carrier block with a fixed, length-delimited canonical coefficient
representation. The candidate set is derived before reading any envelope
fields, and all candidate positions—not a prover-selected subset—are
normalized. Thus changing proof bits does not change `V` or create a hash
fixed-point problem. A mutation to non-carrier syntax changes `V`; mutation to
the carrier set or policy changes `J` or `P`. This intentionally does not
authenticate the original raw cover bytes or the exact carrier symbols: the
proof envelope and proof verification cover the latter, while `V` commits to
the carrier-normalized video. Any different integrity claim needs a separate
mechanism and must be named accurately.

The verifier accepts only its expected `N`, `R`, `root`, `epoch`, and `P`; it
recomputes `V`, `J`, and `S` from the video and local pins. Metadata inside the
video is untrusted input until it matches those values and the proof verifies.
An offline verifier with no outstanding challenge can check proof validity but
cannot claim replay prevention. A public deterministic placement policy has no
secret placement seed; do not claim the seed is hidden. If secrecy of placement
is actually required, the blind extractor needs a separately specified key or
discovery mechanism and that changes the verifier model.

**Application relation.** The application witness is `(payload, opening)`;
the relation checks the exact existing commitment function, not merely a
linear witness that is unrelated to it:

```text
0 < len(payload) <= MAX_PAYLOAD
opening is exactly 32 bytes
payload_commitment = SHA3-256(
  "zkstego/pq-video-statement/v1/payload/" || opening || payload
)
```

The circuit/constraint relation must use a fixed-size canonical witness
encoding: an explicit bounded length, payload bytes padded with zeroes to the
fixed maximum, and constraints that reject nonzero padding or invalid lengths.
The payload and opening are witness-only and never serialized in the envelope.
`S` (including `V`, `N`, relation pins and policy) must be absorbed into the
reviewed backend's Fiat-Shamir transcript before challenges, or be enforced as
public inputs by an equivalent reviewed construction. Merely placing `S` or
its digest in JSON beside a proof is insufficient. The relation proves only
knowledge of an opening for this commitment and context; application-specific
claims about the payload require explicit additional predicates.

**Carrier framing.** A fixed bootstrap prefix of candidate carriers encodes a
small versioned header (magic, envelope version, declared proof length,
statement encoding length, verifier challenge N, and bounded flags) with a specified error-detection
code. The header uses the public canonical order of C; it cannot require a
secret shuffle key because the verifier must locate it before reading the
challenge. Remaining carriers hold the canonical proof envelope, optionally
ordered by a deterministic public function of (N, C, P) so a verifier knowing
its outstanding challenge can reproduce placement without a secret position
map. Header bounds are
checked before allocation; unsupported versions, duplicate/impossible lengths,
insufficient capacity, nonzero reserved fields, extraction ambiguity, or
challenge mismatch fail closed. The header must be parseable without a
sidecar, original cover, secret position map, or prover-chosen relation.
Capacity is the count of eligible carriers after this fixed framing and error
correction overhead, and must be measured on the actual output stream.

This framing is not what the current prototype does: derive_blind_positions_operating_contract()
shuffles candidate positions with sync_key before extracting the header. Its
API requires that shared key, and therefore is video-only with verifier
configuration, not yet the public challenge-derived bootstrap defined here.
The implementation must migrate and test the bootstrap before it can claim
conformance to v3.

**Carrier-set caveat from current code.** build_blind_stable_candidates()
derives one first eligible AC coefficient per luma block, then the embed path
intersects that list with safe_positions derived from the cover stream.
safe_positions includes patchability, CAVLC round-trip/length checks and
policy thresholds; the blind extractor recomputes the same analysis on the
stego stream. Thus it is not inherently unobservable to the verifier, but
equality between cover-derived and stego-derived safe lists is an invariant
that must be established, not assumed. An existing integration test checks
equality for one Foreman CIF fixture and one operating contract, but this is
not proof for every supported Baseline/CAVLC input or policy. In particular,
nal_length_map, validated nC, T1 overrides, coefficient thresholds and parser
support affect eligibility. The v3 implementation must define C by a
specified blind-derivable rule and prove that embedding preserves its
eligibility and patchability decisions (or fail closed); it must not silently
depend on a cover-only decision the verifier cannot reproduce.

**Observed prototype test (2026-09-29).** Ran
`C:\Users\khenh\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q src/runtest/test_video_only_blind_sync_integration.py`
against the checked-in Foreman CIF, 300-frame fixture. Result: **3 passed in
101.75 s**. The real-video case embedded an 8-byte test payload plus the
experimental envelope, extracted it using only the stego video and verifier
configuration, checked direct-vs-fast CAVLC extraction, and observed identical
derived positions plus equal carrier-normalized video digests for this single
cover/stego pair. This is useful evidence for the existing prototype, not a
v3-conformance result: it uses the shared sync key, has no lattice ZK proof,
and covers only one clip/contract. The first system Python lacked pytest; the
explicit Python 3.12 interpreter above was used.
The separate v2 statement-contract runner also passed 9/9 checks, and the
stable-analysis unit test passed 1/1. These test the current contract/helper
scaffold only; they do not validate a lattice proof backend or v3 protocol.

This is a protocol candidate, not a security proof or an implementation
instruction to bypass the current backend gates. The canonicalizer must be
tested against the actual parser/patcher with vectors proving (a) all legal
carrier symbol changes leave `V` invariant, (b) any non-carrier syntax change
changes `V`, (c) policy/position changes alter `J`/`P`, and (d) blind extraction
derives exactly the same `C` before and after embedding. Then an independent
lattice cryptographer must review the relation, statement-to-transcript
binding, challenge/replay semantics, and commitment circuit before v3 can be
implemented or claimed.

### Measured feasibility gate (2026-09-27)

On the current workspace, `LatticeZkProof.create()` produced a JSON transcript
of 131,692 bytes (1,053,536 bits) for a test message. The committed historical
SEC2 operating point reports 1,232 carrier bits (154 bytes): the JSON proof is
about 855× larger than that operating point. Even its raw fixed-width vectors
are far above that budget. These figures are a feasibility warning, not a
claim that every lattice proof system has this size; the prototype is not a
reviewed production proof and must remain disabled.

Re-run this measurement alongside a fresh capacity measurement on each target
asset before integrating any backend. Acceptance requires the exact serialized
proof plus framing to fit the measured, quality-validated capacity, survive
blind extraction and verify from the output video alone. If it does not fit,
record the measured gap and stop that configuration—do not silently move the
proof to a sidecar or report a reference as an embedded proof.

#### Capacity measurement correction (2026-09-27)

The 1,232-bit figure above is the historical SEC2 **operating point**, not the
maximum capacity of that video. The checked-in `sec2_capacity_data.json` also
records 413,415 raw safe candidates for its 300-frame Akiyo asset, while its
quality-validated pool is 1,449 bits and its operating point is 1,232 bits.
Those historical raw candidates are not interchangeable with patchable,
quality-validated capacity. Even the raw count is less than the 1,053,664 bits
needed by the measured experimental JSON proof plus 16 bytes of framing, but
that only rules out that particular 300-frame asset/configuration and
prototype—it is not a general impossibility result for larger videos or other
proof systems.

A fresh forced analysis of `coastguard_cif_q22_g1_3000f.h264` was attempted to
measure its raw safe positions, but the Python whole-video analysis did not
finish: it was stopped after private memory reached about 10.7 GB and was still
growing. No capacity result was produced. The pre-existing native
`zkstego_idr_inspect.exe` separately parsed the 3,000 IDR access units in about
1.7 seconds, but it reports only a small syntax summary; it does not count the
carrier positions, patchability, or quality-validated capacity. These results
must not be conflated.

The bounded-memory raw candidate counter is now implemented in
`benchmark/streaming_capacity_scan.py`; the full measured JSON artifact and
the exact experimental payload are in `benchmark/results/`. The remaining
capacity gate is materially harder: validate enough patchable positions under
the exact embed policy, embed the full serialized bytes into the real stream,
then measure decoding, blind extraction, and quality. Raw candidates alone
must never be treated as usable or validated capacity.

The first chunked raw scan is now available in
`benchmark/results/streaming_raw_capacity_coastguard_3000f_20260927.json`.
It processed the 3,000-frame CIF Coastguard H.264 asset in 30 independently
decoded 100-frame chunks, preserving all frames, with FFmpeg 8.0.1. It counted
4,332,560 raw safe CAVLC candidate bits. The exact experimental JSON artifact
used for this scan was 131,694 bytes; with 16 framing bytes it needs 1,053,680
bits, or 24.32% of that raw count. Thus, unlike the 1,232-bit historical
operating point and the 300-frame Akiyo asset, the 3,000-frame asset has enough
**raw candidates** for this prototype-sized payload. At the time of this raw
scan, patchability, quality, and blind extraction were unvalidated; the SIS
artifact is still an unreviewed research prototype. Total analysis wall time was 1,238.575 seconds (about 2.42
source frames/s for this capacity-analysis command); this is offline scan time,
not embed/verify throughput or a realtime result. Process memory was observed
around 0.8–1.1 GB during polling, but peak RSS was not instrumented and must be
measured in a dedicated benchmark.

The measured video SHA-256 is
`68d707171a2507993ac34baa755f913df5c8fb8131c5f878a2bccab29dead405` and the
proof artifact SHA-256 is
`ff568dd27ae12ae0787325c9dc5ef4603442eaf576b45f3b6453b3c02978ad11`.
The serialized test artifact is retained as
`benchmark/results/lattice_zkp_unreviewed_capacity_probe.json` strictly for
this size/carrier experiment; it is not a reviewed proof or a production ZKP.
Reproduce the capacity scan with the report's input asset and a freshly
serialized prototype artifact using:

```powershell
python -m benchmark.streaming_capacity_scan `
  --video data/encoded/coastguard_cif_q22_g1_3000f.h264 `
  --proof-artifact <exact-serialized-proof.json> `
  --frames-per-segment 100 `
  --ffmpeg D:/Apps/ffmpeg/bin/ffmpeg.exe `
  --ffprobe D:/Apps/ffmpeg/bin/ffprobe.exe `
  --output benchmark/results/streaming_raw_capacity_coastguard_3000f_<run-id>.json
```

### Targeted patchability follow-up (2026-09-27)

The same 3,000-frame source and exact 131,694-byte prototype artifact were then
checked using `_prune_patchable_positions` and `BitstreamPatcher`, with at most
one carrier per block. The run confirmed exactly 1,053,680 positions for the
proof bytes plus 16-byte framing across 30 × 100-frame chunks. The per-chunk
counts were 20 × 35,123 and 10 × 35,122, summing to the exact target. The
patchability-only report is
`benchmark/results/streaming_patchable_capacity_coastguard_3000f_20260927.json`;
it took 3,169.784 seconds (about 0.947 source frames/s for the offline
analysis/patchability scan).

This is stronger than the raw-candidate result: the targeted number of blocks
passed the repository's patcher gate. It is **not** a successful embedding
result: the measurement did not modify or write the video, and the report
explicitly leaves `quality_validated` and `blind_extraction_validated` false.
The scanner stops after confirming the requested target, so those counts do
not measure total patchable capacity or establish zero headroom. The proof
artifact remains an unreviewed prototype rather than an accepted ZKP.

## Phases and non-negotiable gates

| Phase | Deliverable | Acceptance gate | Status |
|---|---|---|---|
| 0 | Claim/threat-model freeze | No use of “ZKP” for an ML-DSA receipt | Done |
| 1 | Canonical public statement | Mutation tests cover every binding; parser rejects tampering; payload opening remains private | Done |
| 2 | Reproducible LaZer target | Pinned source, Linux x86-64 AES+AVX-512F host, demo prove+verify transcript retained | Pending hardware |
| 3 | Reviewed relation | Signed registry gate is scaffolded; fixed public relation proves knowledge of the private payload-commitment opening and any required registered credential, with witness bounds, ZK/soundness parameters, and domain separation reviewed by a lattice cryptographer | Not started |
| 4 | Proof envelope | Versioned binary format carries proof and public statement but not payload/salt; binds verifier-issued session challenge; tamper, truncation, and replay semantics tested | Not started |
| 5 | Native video integration | Patched x264 direct-CAVLC encode → FFmpeg decode → extract → LaZer verify fixture | Not started |
| 6 | Streaming evaluation | p50/p95/p99 latency, bitrate/BER, packet loss/re-encode tests on live transport | Not started |
| 7 | Research evaluation | Multi-dataset/QP/GOP study, modern steganalysis, public baselines, artifact reproduction | Not started |
| 8 | External review | Cryptographic protocol review plus native codec/security review | Not started |

The current host is Windows and the LaZer preflight fails closed (Linux,
x86-64, AES and AVX-512F prerequisites are not all available). The generic
LaZer demo has not run here. This host limitation blocks that backend's local
execution, but does not justify treating the in-tree prototype as an
alternative reviewed proof system.

### Backend feasibility review (2026-09-27)

An upstream-source review confirms the current backend decision rather than
changing the acceptance gate:

| Candidate | Evidence checked | Decision for this system |
|---|---|---|
| LaZer | Its upstream build instructions require Linux x86-64, AES and AVX-512; the pinned library is the project’s intended linear-relation backend. | Keep as the target backend, but do not claim it runs on this Windows host. Provision a supported runner (or obtain a reviewed compatible build) before integration. |
| LNP22 Go probe | The repository describes a NIZK for short linear relations; our fixed CLI passes proof/statement mutation checks. Its repository page provides no independent audit report, and the current probe relation/context construction is not the registered application relation. | Keep isolated under `benchmark/lnp22_context_probe` for research and transport-feasibility experiments only. Do not add it to the production registry or claim application-level security. |
| Lattirust | Its own README says it is for research/prototyping, has not been audited, and is not fit for real-world deployment. | Not a production substitute. Revisit only with a protocol/relation review and implementation audit. |

Sources: [LaZer build requirements and demos](https://github.com/lazer-crypto/lazer/blob/main/README.md), [LNP22 Go repository](https://github.com/KarpelesLab/lnp22), and [Lattirust security statement](https://github.com/lattirust/lattirust#security). These pages establish project claims and requirements, not independent certification. The next backend gate remains obtaining a host that passes `python -m src.lazer_backend`, then running the pinned LaZer demo and retaining its transcript; backend selection alone does not complete the reviewed relation, proof envelope, or video pipeline phases.

### Runtime/API evidence recheck (2026-09-28)

- `py -3.12 -m src.lazer_backend` returned `ready: false` for the Docker-visible
  Linux x86-64 host. Docker was available and `aes` was present, but
  `avx512f_required` was the blocker. Rebuilding the same image cannot supply
  that missing CPU instruction; the LaZer execution gate needs a compatible
  runner or a separately reviewed backend.
- A saved older demo log records `/api/v1/jobs/verify` returning `501 Not
  Implemented`; that is historical evidence and does not describe the current
  API source. The current workspace contains the loopback-only experimental
  API in `benchmark/lnp22_context_probe/http_api.py` and custom contract tests
  in `src/runtest/test_lnp22_http_api.py`. Running
  `py -3.12 src/runtest/test_lnp22_http_api.py` passed 7/7 tests for auth,
  upload/job contracts, download, path confinement, storage/rate limits, and
  loopback binding. Those tests use stubbed operation runners: they do not
  establish a real HTTP-to-H.264-verifier E2E pass, nor do they make the
  experimental probe a production API.
- A targeted source review found useful local safeguards: the server refuses
  non-loopback binds, compares bearer tokens with `hmac.compare_digest`,
  validates workspace-relative paths and `.h264` names, limits upload/inbox
  bytes, rejects transfer encoding, stores uploads via same-directory
  temporary files plus atomic hard-link publication, and redacts worker
  exception details. However, there is no client request/socket read timeout,
  no TLS/remote-bind mode, and no actual HTTP-to-real-verifier E2E result. Keep
  this API loopback-only; this targeted source review is not a penetration
  test or production security approval.
- The protocol-v2 3,000-frame probe run reached 27/30 stego segments, all of
  which passed segment-level strict H.264 decode. Windows event 1074 records a
  user-context power-off at 07:52:24 on 2026-09-28, followed by Event Log
  service stop at 07:52:33 and a reboot at 08:29:48. The process was gone and
  no final video/report existed; classify this as interrupted, not as a
  pipeline pass or exception.
- A fresh run started at 08:47:54 on the same 3,000-frame input with current
  source protocol `zkstego/lnp22-video-transport-probe/v3` (Python PID 2884,
  launcher PID 28348). It uses a newly provisioned fixed relation and keeps
  the witness in `%LOCALAPPDATA%/zkstego/lnp22`; output/report and stdout/stderr
  have distinct `lnp22_video_e2e_retry_20260928T084753.*` names. At 08:51 it
  was live and had created the provisional proof, but no final video/report
  existed yet. This remains the experimental LNP22 relation, not the reviewed
  application ZKP required by the goal.
- At 08:53 PID 2884 remained live in carrier/context analysis. Its temporary
  workspace contained 30 source segments and no stego segments. Windows showed
  329.8 CPU seconds and about 1.02 GiB instantaneous working set; these are
  snapshots, not peak-RSS or completed benchmark data.
- At 08:55:55 it was still in the same phase with no stego output; CPU time
  reached 449.9 seconds and working set 1.19 GiB. Compared with 08:53:52 this
  indicates continued CPU-bound work and increasing resident memory, not a
  measured peak or completed performance result.
- At 08:58:10 it remained live with 30 source segments and no stego segments;
  CPU time was 580.3 seconds and working set 1.54 GiB. This is another
  instantaneous sample, not peak RSS; the memory rise is a resource-risk signal
  requiring peak measurement and analysis after this run.
- At 08:59:50 it was still active with no stego output. Windows reported 679.2
  CPU seconds, 1.71 GiB OS-maintained process high-water working set, and 2.30
  GiB private commit. This excludes any recursive child-process peak and is not
  the final instrumented run-level RSS result.
- At 09:03:54 it remained active with no stego output: 912.5 CPU seconds, 1.95
  GiB process working-set high-water, 2.54 GiB private commit. Host counters
  sampled 1.21 GiB available and 26.97/43.63 GiB committed, with 0 pages/sec at
  that instant. This is not a guarantee of future headroom or the process-tree
  peak; continue monitoring.
- At 09:05:09 it was still active with no stego output. Current working set was
  1.33 GiB, process high-water 2.05 GiB, private commit 1.92 GiB and host
  available RAM 1.76 GiB. This shows fluctuating memory use, not a monotonic
  rise; the process-tree peak report remains pending.
- At 09:07:44, after about 20 minutes elapsed, it was live with 30 source
  segments and no stego output. CPU time rose 84 seconds over the preceding 86
  seconds, confirming continued CPU-bound work rather than a stalled process.
  Working set was 1.54 GiB, process high-water 2.05 GiB and private commit
  2.12 GiB; carrier analysis was still incomplete.

## Relation-design decision required before Phase 3

The proof must use an **independently known public statement**. A sidecar signer
choosing both a statement and witness proves nothing useful. The recommended
first relation is a registered-device lattice commitment: the verifier has a
registered commitment/public relation key, while the prover proves knowledge of
its short opening and binds the canonical video statement through the proof
transcript. A separate issuer/policy credential is needed if the claim is
authorization rather than device possession.

### Candidate v1 relation (proposal only; not implemented or reviewed)

Use the issuer-pinned relation descriptor to fix a ring
`R_q = Z_q[X]/(X^d + 1)`, public matrix `A ∈ R_q^(n×m)`, registered target
`y ∈ R_q^n`, and coefficient-norm bound `B`. The witness is a short vector
`s ∈ R_q^m`. This matches the form of the pinned LaZer linear-relation demo;
the exact embedding of the registry key and bounds into its generated
parameters still needs an executable fixture. The proposed language is:

```text
R_device((A, y, q, d, B), s) = 1
    iff  A·s ≡ y (mod q, X^d + 1)  and  ||coeff(s)||_2 ≤ B.
```

The LaZer demo API expresses the same equation as `A·s + t = 0`; encode the
registered target as `t = -y` when constructing that public statement. Do not
assume that a Python-level `set_statement(A, t)` call alone defines the
registry, norm policy, or video context.

The relation ID commits to the canonical descriptor, verifier parameters,
verification-key/artifact digests, and admissible codec policy. The verifier
loads those values from its pinned, issuer-authenticated registry snapshot; it
does not trust a relation descriptor or trust anchor supplied by the video.
The statement supplied to the proof API is the exact canonical public byte
string from `VideoZkpStatement.to_public_bytes()`, with `statement_id` checked
by recomputing it. The proof transcript must absorb, under a distinct protocol
domain, the relation ID, registry root and epoch, and every byte of that
canonical statement **before deriving any Fiat–Shamir challenge**. A mutation
to session, payload commitment, either video digest, carrier-position digest,
policy, or registry binding must therefore produce a different transcript
and fail verification. If the pinned backend API cannot bind this complete
context, this relation is not integrated until the protocol is extended and
reviewed; putting `statement_id` in an unauthenticated envelope is not enough.

Source review of the pinned LaZer revision (`10eafeca4cd53ff4fc54193dce904dbd0026fefd`)
found that `__lnp_hash_pp_and_statement()` absorbs `state->ppseed` and the hash
of its algebraic statement before proof commitments, and the generic Python
demo sets that statement with `set_statement(A, t)` ([pinned source](https://github.com/lazer-crypto/lazer/blob/10eafeca4cd53ff4fc54193dce904dbd0026fefd/src/lin-proofs.c#L4247-L4260),
[pinned demo](https://github.com/lazer-crypto/lazer/blob/10eafeca4cd53ff4fc54193dce904dbd0026fefd/python/demo/demo.py#L10-L43)).
The demonstrated API does not expose a separate video-context argument.
Prefer testing an algebraic context-binding extension while leaving LaZer's
public-parameter seed unchanged. For a prime registered modulus `q`, hash the
full canonical statement to a 256-bit integer `u`, then encode `u` injectively
as base-`(q-1)` digits `d_i ∈ [0,q-2]`. Let `k` be the least integer for which
`(q-1)^k ≥ 2^256`, and set `h_i=d_i+1`; each `h_i` is nonzero and thus a unit
modulo prime `q`. Extend the registered relation with `k` rows and witness
elements:

```text
A' = diag-block(A, h_0, …, h_(k-1))
y' = (y, h_0, …, h_(k-1))
s' = (s, 1, …, 1)

A'·s' = y'   iff   A·s = y and each h_i·s'_i = h_i.
```

The auxiliary witness elements must be constrained to coefficient infinity
norm at most 1. Since each `h_i` is a unit, the added equations force
`s'_i = 1` in the ring, leaving the registered device relation unchanged. The
encoded statement digest is represented injectively in the public augmented
matrix/target, which the pinned implementation hashes as part of its algebraic
statement before proof commitments. For LaZer, pass the negated augmented
target because its demo writes the equation as `A·s + t = 0`. The upstream
demo uses `q = 2^32 - 4607`; for that modulus, `(q-1)^8 < 2^256`, so this
encoding needs nine added rows/witness elements. The actual application
parameters may use a different prime modulus and therefore require a new
calculation.

This is a **candidate construction**, not yet proven secure or implemented.
It relies on statement-hash collision resistance, the fixed registry relation,
prime-field arithmetic, exact norm enforcement for auxiliary witnesses, and
the pinned protocol's statement hashing; its proof-size and runtime overhead
are unmeasured. Confirm all of these against the exact generated LaZer
parameters, implement prover/verifier symmetry, and obtain independent review
before adoption. If those checks fail, the alternatives are an explicitly
reviewed LaZer transcript-context extension or an independently justified
statement-derived `ppseed`; the latter also seeds LaZer's auxiliary public
parameters and cannot be changed casually. This LaZer-specific candidate has
not been implemented or run.

Separate implementation evidence exists for the experimental LNP22 transport
probe: `fixed.go` implements a context-derived determinant-one row transform
and `fixed_relation_test.go` exercises proof rejection under context changes.
That transform is invertible and preserves the same short-witness solution
set for every context; its demonstrated effect is to bind the proof transcript
to the serialized context, not to make the context fields substantive
predicates of the relation. The probe's Python verifier independently checks
the extracted payload commitment, carrier-position digest, and
carrier-normalized video digest, but those checks are outside the ZK relation.
This is not evidence that the LaZer construction above works, and neither
construction has received independent cryptographic review.

This candidate proves only knowledge of a short opening for the registered
lattice target, and that this proof instance is bound to the supplied video
statement. It does **not** prove that the hidden payload opens
`payload_commitment`, that the prover performed the encoding, or that every
H.264 coefficient was produced by an approved encoder. In particular,
`payload_commitment` is currently a context field, not a proved hash preimage
relation. If the product claim requires proving knowledge of that opening, add
and analyze a separate relation that proves it; do not infer that guarantee
from statement binding. The blind verifier also cannot validate the raw cover
video hash without the cover itself; bind and recompute a precisely specified
carrier-normalized video commitment instead. Likewise, the verifier must derive
and validate the position policy itself. A proof bound to a prover-chosen
`positions_hash` alone does not establish where the proof was embedded.

### Payload privacy is an explicit unmet target (2026-09-28)

The top-level target claim requires that the payload and placement seed remain
private. The current transport probe does not meet this requirement:
`encode_video_probe_payload()` serializes `payload_bytes` in the in-video
envelope, and the blind decoder returns those bytes. Its 3,000-frame test
payload is intentionally public. The probe's `payload_commitment` is recomputed
by Python against that disclosed payload; LNP22 only proves the provisioned
short linear-relation witness. Thus the proof does not establish a hidden
opening of the payload commitment.

The intended private witness includes `(payload, opening)` and must prove the
exact commitment equation already defined by statement-v2, not an alternate
hash invented by the proof adapter:

```text
payload_commitment = SHA3-256(
  b"zkstego/pq-video-statement/v1/" || b"payload/" || opening_32 || payload
)
```

This is the byte sequence produced by `src/video_zkp_contract.py::payload_commitment`
and is now pinned by the Python reference vector in
`src/runtest/test_video_zkp_contract.py`. It is **not** an independent circuit
fixture. The verifier must independently fix
the hash, domain, 32-byte opening format, maximum payload length, and relation
version. The current Python commitment helper has no maximum-length argument,
so it is not yet a complete circuit input contract. Add an explicit bound and
canonical witness encoding before compiling a circuit. If the preimage format
is changed to add a length prefix or relation ID, bump the statement/hash
protocol version and update its reference vector; do not silently create a
second meaning for `payload_commitment`.

The proof transcript must bind that public commitment together with the
verifier-recomputed carrier-normalized video digest, deterministic
position-policy result, codec policy, registry root/epoch, and session
challenge. The payload and opening must not be included in the extracted
envelope. A proof of a linear relation whose target is merely derived from a
context hash is not a substitute for this hash-preimage constraint.

### Alternative statement-v4 research route: lattice commitment opening (proposal only)

The SHA3-preimage requirement above is the current v3 contract and must not be
silently weakened. Since the chosen lattice backends expose bounded linear
relations more directly than SHA-3 circuits, a separately versioned v4 could
replace the payload hash commitment with a *lattice vector commitment* whose
opening relation is itself linear. This is only a construction candidate; no
v4 code, parameters, proof, or cryptographic review currently exists.

For a fixed public maximum payload length `Lmax`, let the verifier obtain the
actual length `L` from the canonical public statement (length leakage is
explicit). Encode the `8*Lmax` payload bits as pairs `(u_i, v_i)` and enforce
the backend's coordinate bound `||s||∞ <= 1` on the *entire* witness vector
`s=(r,u,v)`. Add a public linear row `u_i + v_i = 1`; since `q > 4`, the
integer bound makes the only modular solutions `(0,1)` and `(1,0)`, so one
coordinate is an exact bit. Rows for positions beyond `8*L` additionally
constrain the payload bit to zero. Use a random short vector `r` whose
coordinates are in `{-1,0,1}` and a
domain-separated, verifier-pinned matrix to form a hiding commitment
`C = A_r*r + A_p*b (mod q)`. The full relation stacks (a) bit-pair rows,
(b) zero-padding rows, and (c) the commitment equation into one fixed bounded
linear statement `M*s = t (mod q)`. The payload remains the ZK witness; only
`C`, `L`, policy/context and the proof are public.

**Hiding feasibility gate for this construction.** These equations do not by
themselves prove that `C` hides `b`. For statistical hiding via a random linear
map, let `A_r` be uniform in `F_q^(n x m)` and let `r` have independent,
uniform ternary coordinates. The leftover-hash-lemma condition is
`m*log2(3) >= n*log2(q) + 2*lambda` for statistical distance at most
`2^-lambda`, assuming the matrix family is universal and independent of `r`.
At the Ringo example scale `q ~= 2^220`, with `n=8192` commitment elements and
`lambda=128`, this requires at least **1,137,249 ternary randomness
coordinates** (about `138.8*n`), not `n` coordinates. This is a bound for
that statistical-hiding construction, not an impossibility result for all
computationally hiding lattice commitments. A computational-hiding variant
must name and analyze its actual assumption, dimensions, norm bound, entropy,
and multi-use behavior. Until one of these hiding arguments is provided, the
v4 equation is a binding-relation sketch, not an accepted private commitment.
See the [leftover-hash lemma](https://eprint.iacr.org/2022/1733.pdf) for the
min-entropy requirement.

This is materially different from proving a SHA3 opening and therefore
requires a new protocol/domain version, registry descriptor, parameter set,
test vectors, and independent review. Soundness requires that the backend
really enforces the coordinate bound and extracts a witness; `q` must prevent
modular wraparound for every short linear row. Hiding and binding of
`C` require a concrete lattice commitment analysis (including entropy of `r`,
matrix derivation, SIS parameters, multi-use behavior and message length), not
just the backend's ZK property. The relation binds a payload to `C`; it still
does not prove H.264 encoder correctness. The verifier must fix or authorize
the expected `C` under application policy, and must derive video/session
context and bind it into the canonical statement/transcript to prevent
prover-selected claims and replay.

This route is worth a feasibility gate because its payload predicate is linear
once bitness is encoded by bounded coordinate pairs; it avoids invoking the
generic SHA-256 circuit that is incompatible with ISW21's small characteristic
field. It does **not** justify calling the in-tree homemade SIS transcript or
the short LNP22 probe an accepted ZK backend. The next evidence must be a
reviewed backend's exact norm semantics plus a small executable relation test
for bitness, zero padding, and commitment opening, followed by independent
soundness/ZK/commitment review and measured proof size. If that fails, retain
the existing v3 requirement and report the circuit/backend blocker rather than
claiming v4 completion.

Current integration status remains a blocker even for this linear candidate:
`src/lazer_backend.py` pins and permits only the upstream `A*s=t` smoke demo;
it does not expose an application-relation prover/verifier API, and the pinned
LaZer runtime cannot run on this host because AVX-512F is unavailable. Thus
this construction has not been compiled against LaZer or connected to the
registry/video pipeline.

The reviewed source candidates show that lattice-based R1CS proofs exist in
the literature: the LaBRADOR paper specifies a lattice-based argument for
R1CS and discusses concrete proof sizes, while current Rust implementations
are explicitly research-stage. The [Lazarus repository](https://github.com/lattice-complete/Lazarus)
lists a binary-R1CS frontend in its roadmap and warns that the API is under
active development and not for production; [Lattirust](https://github.com/lattirust/lattirust)
describes itself as research/prototyping software that is unaudited and not
fit for real-world deployment. The pinned LaZer integration in this repository
has only exercised its linear-relation demo, not an SHA-256 circuit. These
facts justify a **research feasibility prototype**, not choosing one of these
implementations as an accepted production backend. Any hash circuit must be
compiled from a reviewed source relation, checked for under-constraints, and
benchmarked for proof size, memory, and proving time before it can be embedded.

Until that circuit-capable lattice backend and relation pass those gates, the
privacy requirement remains **not implemented**. Do not remove payload bytes
from the current envelope and claim success: doing so without a valid opening
proof would make the payload commitment unverifiable rather than private.

No concrete `q`, dimensions, norm bound, security level, rejection/soundness
error, zero-knowledge definition, or proof-size bound is selected here. Those
are protocol parameters, not tuning guesses: the relation descriptor must pin
them and their derivation, the exact LaZer revision/API must be exercised on a
supported host, and an independent lattice-cryptography review must approve
the relation and Fiat–Shamir transcript before any security claim. Until then,
this is a scoped design proposal only; the application's production ZKP remains
unimplemented.

Do not implement a hash circuit or an “all CAVLC coefficients changed correctly”
relation until its witness, cost and threat model are specified. The first is a
general PQ proof-system task; the second is a large codec-verification task and
is incompatible with a real-time claim unless independently benchmarked.

## Immediate execution instructions

1. Provision a Linux x86-64 host whose Docker-visible CPU flags include
   `avx512f` and `aes`.
2. Run `python -m src.lazer_backend`; it must return `"ready": true`.
3. Build and run the pinned LaZer demo as documented in `lazer/README.md`.
4. Save the prover/verifier output, CPU model, compiler/Sage versions and image
   digest as a test fixture.
5. Specify the application relation and publish it in an issuer-signed
   `lazer-v1` registry. Verifiers must pin that issuer public key out of band;
   they must not accept a trust anchor supplied by a video sidecar.
6. Only then implement Phase 3 against the exact LaZer API and generated
   relation parameters—not the disabled in-tree prototype.

## Publication gates

- **Q2-ready systems paper:** phases 0–2, 4–7, with a narrow
  PQ-authenticated-steganography claim; a lattice ZKP is not required.
- **Q1 PQ-video-ZKP claim:** all phases, a novel/reviewed relation, soundness
  and zero-knowledge analysis, independent cryptographic review, and a broad
  video/steganalysis/realtime evaluation.

### Live E2E run status recheck (2026-09-28 15:28 +07:00)

- The 3,000-frame Coastguard run started at 11:09:43 +07:00 as PID 19668 with
  `--proof-mode compact`, input
  `data/encoded/coastguard_cif_q22_g1_3000f.h264`, and intended outputs
  `benchmark/results/lnp22_video_e2e_compact_20260928T1109.h264` and
  `.json`. Its progress JSONL last changed at 13:18:06 +07:00 and still ends
  at `blind_extract_verify/started`; no extraction segment, final output, or
  final report event/file is present. Do not classify this run as completed.
- The candidate artifact already exists at
  `benchmark/results/lnp22-video-e2e-3iaq4hb0/candidate.h264` (98,479,704
  bytes). The recorded embed phase used 86,232 carriers and passed strict
  H.264 decode, but blind extraction and cryptographic verification remain
  unconfirmed.
- At 15:28:43 +07:00 the Python process was still live and CPU-active: CPU
  time 14,775.6 s, current working set 1.93 GiB, process high-water working
  set 3.59 GiB, current private commit 2.53 GiB, and process peak pagefile
  usage 4.19 GiB. Host available physical memory was 2.40 GiB. These are
  Windows process/host snapshots, not process-tree peak RSS or a completed
  benchmark; no child process was present in the immediate process query.
- This PID loaded source before the subsequent blind-extraction decoded-block
  fast path and extraction-split telemetry were added. Its long runtime must
  not be used to estimate those changes. The process is still advancing CPU
  time, so this status check does not terminate or restart it; continue polling
  this same PID and its report/output paths. A later run is needed to capture
  the new per-phase extraction telemetry.

### Candidate quality measurement and E2E recheck (2026-09-28 15:41 +07:00)

- A complete, independent luma-quality run was produced for the embedded
  candidate above. The source is
  `data/encoded/coastguard_cif_q22_g1_3000f.h264`; the candidate is
  `benchmark/results/lnp22-video-e2e-3iaq4hb0/candidate.h264`. The machine-
  readable report and all 30 source/stego segment inputs are retained in
  `benchmark/results/quality_lnp22_video_e2e_20260928T153429/`.
- The report states `complete: true`, 30/30 segments and 3,000/3,000 frames.
  It compares decoded source H.264 with decoded stego H.264, measuring Y/luma
  only; the quality helper forces both streams to 352x288. FFmpeg reports
  version 8.0.1. Full-frame-set PSNR is 49.6066 dB, with 2,100 frames having
  identical luma (infinite PSNR). For the 900 changed-luma frames, PSNR p05,
  median and p95 are 39.6892, 45.8694 and 53.9837 dB; minimum across all
  frames is 35.4652 dB. Mean per-frame SSIM is 0.999884; p05 is 0.999431.
- These figures describe this one CIF source/candidate pair only. They do not
  measure chroma, raw-camera quality, other codecs/resolutions, bitrate impact,
  steganalysis resistance, or proof validity. The JSON explicitly records
  these limitations and contains per-frame and per-segment records and input
  segment hashes. This result validates candidate visual-quality measurement,
  not extraction or verification.
- Rechecking PID 19668 at 15:47:53 +07:00 showed the process still present and
  CPU-active (15,838.8 CPU seconds; 2.04 GiB working set; 2.65 GiB private
  commit). Its progress log still ends at `blind_extract_verify/started`, with
  no terminal phase event or final report. The run is therefore still
  incomplete; preserve and continue polling it rather than declaring success
  or restarting solely due to elapsed time. Its resource snapshots are not a
  completed-run benchmark.
- The existing `carrier_context` and `embed` completion events in the JSONL
  both report `segments_total=9`, which came from the older probe source and is
  mislabeled: 9 is the number of payload-bearing segments used, not the 30
  total video segments. The current source now emits `segments_used` for both
  completion events; the already completed run's historical log remains
  unchanged.

### Completed prototype video-only E2E (2026-09-28 15:51 +07:00)

- PID 19668 terminated normally after producing
  `benchmark/results/lnp22_video_e2e_compact_20260928T1109.h264` and
  `benchmark/results/lnp22_video_e2e_compact_20260928T1109.json`. The JSON
  reports `blind_video_only_extraction: true`, `strict_h264_decode: true`,
  `proof_verification: true`, and nested `verification_result.valid: true`.
  It identifies protocol v3, proof format LNPF-v2, statement id
  `dc80e949846f705fe50182531c3a67b3fb66b20040b9e6d1d896ea3ac2e30ddd`, and
  output SHA-256
  `3537250821090b0b4fb08a51429f640ce736857ea6026a1c59086633f99b226b`.
- This run used the 3,000-frame, 352x288 Coastguard input. It embedded a
  9,227-byte experimental proof in a 10,446-byte payload across 9 of 30
  100-frame segments, consuming 86,232 carrier bits. The output is
  98,479,704 bytes and passed strict H.264 decode. The independent quality
  report above was generated from this run's temporary candidate before the
  temporary directory was removed; the probe publishes that candidate to the
  requested output using a hard link, so those measured bytes are the output
  artifact.
- Measured phase durations: cover analysis/carrier selection 3,229.54 s;
  proof generation 21.52 s combined; embed plus strict decode 4,450.90 s;
  blind extraction plus verification 9,229.57 s. Total measured pipeline time
  before artifact publication was 16,931.57 s (about 4 h 42 min), with peak
  process-tree RSS 3,664.95 MB. Throughput was 0.177 frames/s, far below
  realtime. Cryptographic verification itself took 6.539 ms after extraction;
  video analysis/extraction dominates. This is one development-host run, not a
  representative performance distribution.
- Scope remains explicitly experimental: the relation and private witness
  were provisioned separately; the proof establishes knowledge of the pinned
  short linear-relation witness only. It does not prove the payload-commitment
  opening or H.264 encoder correctness, and has no independent cryptographic
  audit. This is a real video-only transport/extract/verify pass for the probe,
  **not** acceptance of the application's lattice ZKP or production security.

### Independent full-file decode check (2026-09-28)

- Rechecked the published 98,479,704-byte output independently with FFprobe:
  H.264 Constrained Baseline, 352x288, exactly 3,000 decoded frames.
- Ran FFmpeg over the complete file with `-v error -xerror` and decoded to a
  null sink; exit code was 0. Recomputed SHA-256 was
  `3537250821090b0b4fb08a51429f640ce736857ea6026a1c59086633f99b226b`, matching
  the E2E report. This confirms the current artifact is decoder-readable; it
  does not upgrade the experimental LNP22 relation's security scope or the
  earlier report's performance/realtime limitations.

### Standalone blind-verification timing recheck (2026-09-28 16:23 +07:00)

- A separate video-only `verify` invocation is now running against the
  published output above, using the pinned relation digest. Its distinct
  artifacts are `benchmark/results/lnp22_video_e2e_compact_20260928T1109.verify.log`
  and `.verify.json`; the JSON is still zero bytes while the process runs and
  must not be treated as a result.
- With the new extraction progress telemetry, the splitter validated all 30
  100-frame segments (3,000 frames). Segment 0 completed in 636.309 seconds
  and segment 1 in 610.793 seconds; segment 2 completed in 613.792 seconds.
  Each extracted 10,296 carriers. Segment 3 has started. At 16:23:13 +07:00
  PID 34444 was still CPU-active (1,935.3 CPU seconds, 1.73 GiB working set,
  2.32 GiB private commit). The `.verify.json` remains empty while the run is
  active. Wait for this same process and
  require a parseable final JSON with `valid: true` before recording standalone
  verification as passed. These two segment samples are not a p50/p95
  distribution or a completed-run throughput.

### Local HTTP API request timeout hardening (2026-09-28 16:34 +07:00)

- Added `ApiConfig.request_timeout_seconds` (finite positive value, default 30 s)
  and apply it to each accepted HTTP connection before request parsing. This
  bounds idle/slow-client socket operations; it does not time-limit or cancel
  a running proof job. The service remains loopback-only and experimental.
- Added raw-socket regression coverage for incomplete HTTP headers and an
  upload that stalls after partial body bytes. It verifies the connection
  closes at a configured 150 ms inactivity timeout and leaves neither a
  published partial video nor a temporary upload file. TDD result: the test
  first failed because `ApiConfig` did not accept the timeout; after
  implementation, the complete custom API suite passed 8/8 and Ruff passed
  for the API and its test file.
- These API contract tests use an inline executor and stub operation runners;
  they do not constitute a live HTTP-to-real-ZKP end-to-end test, TLS support,
  or an independent security audit.

### Standalone verification process poll (2026-09-28 16:42 +07:00)

- PID 34444 is still the same live standalone video-only verification process.
  Its CPU time and working set have advanced since the preceding poll (current
  working set about 1.92 GiB), so retain it; do not restart it.
- The progress log still shows extraction segments 0–3 complete and segment 4
  in progress, started at 16:33:48 +07:00. The final JSON remains 0 bytes, so
  this verification is not yet a result. The observed ~10-minute-per-100-frame
  segment cost confirms this path is far from realtime; the rest of the video
  must still be processed or safely skipped after declared payload chunks are
  recovered and carrier-normalized digests are collected.

### Standalone verification progress (2026-09-28 16:45 +07:00)

- Re-polling the same PID 34444 confirmed continued CPU activity. Segment 4
  completed at 16:44:26 +07:00 after 638.116 s and extracted 10,296 carriers;
  segment 5 then started. This is about 0.157 frames/s for that 100-frame
  segment, consistent with the previous segments and not realtime.
- The verification report is still empty while PID 34444 runs. Do not mark the
  standalone verification passed until that process exits and its JSON parses
  with `valid: true`.

### Streaming regression suite and verification poll (2026-09-28 16:55 +07:00)

- `py -3.12 -m pytest src/runtest/test_blind_sync_streaming.py -q` completed
  with **5 passed in 143.09 s**. This includes the real 30-frame IDR H.264
  chunked embed/extract round trip; the other tests cover segment progress,
  declared chunk handling, global position/digest context, and embed progress.
  The focused real-video integration test also passed independently (1/1,
  141.08 s). These are bounded transport tests, not proof of realtime or ZKP
  relation security.
- PID 34444 remains active. Segment 5 completed in 606.850 s and segment 6
  started at 16:54:32 +07:00; the standalone JSON is still empty. Continue
  polling this same process and require a parseable `valid: true` result.

### LNP22 probe regression checks (2026-09-28 16:58 +07:00)

- In `benchmark/lnp22_context_probe`, `go test ./...` passed (4.723 s) and
  `go vet ./...` exited successfully. These exercise the experimental fixed
  relation/proof serialization and tamper tests in the Go probe; they do not
  independently validate the LNP22 security proof or make this an accepted
  application relation.
- The Python streaming suite remains 5/5 passed (143.09 s), including the
  real H.264 chunked round trip. PID 34444 is still live at segment 6, with
  CPU time advanced to about 3,716 s; its standalone verification JSON remains
  empty. Preserve the process and wait for terminal report evidence.
- `py -3.12 -m pytest src/runtest/test_lnp22_video_e2e.py -q` passed **30/30
  in 2.04 s**, including strict envelope parsing, payload-commitment mismatch,
  statement/context mutations, relation-pin enforcement, position/video
  commitment mismatch, proof-format routing, and a real Go LNP22 proof round
  trip. These tests validate probe behavior; the Go relation still is not an
  independently reviewed application proposition.

### Standalone verification recheck (2026-09-28 17:04 +07:00)

- The same PID 34444 remains present and CPU-active. Segment 6 is still in
  progress 615 seconds after its 16:54:32 +07:00 start; no completion event
  has been emitted yet. Working set is about 2.05 GiB and continues to vary.
  The standalone result JSON remains 0 bytes. This is slow but not a stalled
  process by CPU evidence; preserve and poll the same run.

### Standalone verification segment 6 completed (2026-09-28 17:07 +07:00)

- PID 34444 completed extraction segment 6 at 17:05:10 +07:00 after 638.118
  s, yielding 10,296 carriers; segment 7 started immediately. The report JSON
  remains empty. The repeated per-segment time is direct evidence that this
  current full-video extraction implementation is not realtime; this run must
  continue for verification evidence, while any future optimization needs a
  separately measured run.
- Source inspection confirms `_extract_bits_from_decoded_analysis` and H.264
  bitstream parsing are currently Python paths. The native
  `zks_cavlc_extract_block_bit` helper accepts already-decoded coefficient
  arrays and does not parse the input bitstream or discover blind carriers, so
  it is not a drop-in acceleration for this verifier. A safe native speedup
  would first need a bitstream-level extraction implementation plus differential
  tests against the Python parser; no such substitution was made in this turn.

### Probe README evidence correction (2026-09-28 17:11 +07:00)

- Corrected `benchmark/lnp22_context_probe/README.md`, which incorrectly said
  no real full-proof video run existed. It now cites the completed 3,000-frame
  run, proof/envelope/carrier sizes, strict decode, video-only extraction and
  verification claim from its JSON, as well as its 0.177 FPS and peak RSS; it
  explicitly labels this one experimental development-host result and
  separates it from the still-running standalone recheck.
- `git diff --check` found no whitespace errors in the two documentation
  edits. PID 34444 remains CPU-active at segment 7 and `.verify.json` is still
  empty; no independent recheck conclusion can yet be recorded.
- A follow-up call-graph check found the fixed Go CLI is invoked by
  `video_e2e.py`, and `http_api.py` delegates its operation runner to
  `embed_and_verify`/`_verify_from_video`. The README now accurately says the
  probe components are wired together, while its HTTP tests use stub runners
  and it is not a production API or registered application relation.

### Standalone verification segment 7 completed (2026-09-28 17:16 +07:00)

- PID 34444 remains CPU-active. Segment 7 completed at 17:15:43 +07:00 after
  633.110 s, yielding 10,296 carriers; segment 8 started. The standalone JSON
  remains empty, so keep this process running and do not record a verification
  result yet.
- The progress log now provides eight sequential 100-frame extraction timings:
  636.309, 610.793, 613.792, 634.667, 638.116, 605.850, 638.118, and 633.110
  seconds. Their median is 633.889 s/100 frames (0.158 FPS); min/max are
  605.850/638.118 s. These are segments from one video in one verification
  run, not independent samples, so they are not a p95/p99 or cross-video
  distribution. The JSON report remains the required evidence for final
  end-to-end verification timing.

### SEC5 benchmark classification and rerun (2026-09-28)

- Corrected `benchmark/sec5_zkp.py`: the prior P-256 code was ECDSA signing,
  not Schnorr and not a zero-knowledge proof. The new schema places ECDSA in
  `signature_baselines` with `zero_knowledge: false`; ZKP plots use only the
  separate `proof_systems` group.
- Removed fabricated Groth16 timing adjustments (subtracting 800 ms from
  proving and hard-coding verification to 8.5 ms). The new measurement records
  end-to-end bridge wall time including subprocess overhead, reports proof
  bytes separately from packed proof-bearing payload bytes, and fails instead
  of substituting guessed Groth16 values if the real run fails.
- Ran `py -3.12 benchmark/sec5_zkp.py --force` successfully. New artifact
  `benchmark/results/sec5_zkp_data_new.json` records three Groth16 trials:
  129 B proof, 147 B packed payload, mean 7,042.44 ms prove and 2,208.23 ms
  verify. Fifty ECDSA trials averaged 70.88 B, 0.623 ms signing, and 0.256 ms
  verification; these are signature baselines, not ZKP numbers.
- The new JSON explicitly marks PLONK/STARK/Bulletproof figures as unexecuted
  literature estimates and non-comparable. They remain unsuitable for an
  apples-to-apples quantitative claim. This SEC5 harness measures Groth16, not
  the experimental lattice proof; it does not close the primary ZKP goal.
- Generated `sec5_proof_size_new.png`, `sec5_timing_new.png`, and
  `sec5_properties_heatmap_new.png` without overwriting the historical files.
  Regression tests: `py -3.12 -m pytest
  src/runtest/test_sec5_zkp_benchmark.py -q` → 2 passed; Ruff, py_compile, and
  `git diff --check` also passed.
- The long-running standalone LNP22 video-only verifier is now terminal: PID
  34444 is absent; its JSON parses with `valid: true`, `proof_bytes: 9227`,
  `carriers_used: 86232`, and `verify_ms: 5.309`. This confirms that particular
  experimental pinned-relation proof check, not independent cryptographic
  soundness, application-relation acceptance, or real-time extraction.

### LaZer host preflight recheck (2026-09-28)

- Reran `py -3.12 -m src.lazer_backend`: Docker-visible host is Linux/x86-64,
  Docker is available, AES is present, `ready: false`, blocker only
  `avx512f_required`. The physical CPU reported by Windows is Intel Core
  i7-12700H and does not expose AVX-512F.
- This corrects older wording that Docker was unavailable. The blocker is now
  ISA support, and rebuilding the container on this host cannot satisfy it.
  No LaZer proof was attempted because the fail-closed preflight refused this
  incompatible host. The next executable LaZer step requires a compatible
  runner (or a separately reviewed backend); the application relation and
  video integration are still outstanding independently of hardware.

### Lattice proof backend selection checkpoint (2026-09-28)

- **LaZer** remains the strongest general lattice-relation candidate in the
  local comparison, but this host cannot execute it: the upstream build/run
  requirements specify Linux x86-64 with AVX-512 and AES, GCC >=13.2, and
  SageMath >=10.2; local preflight found no AVX-512 on the i7-12700H. Its repo
  documents a general `A s = t` demo, but availability of that demo alone does
  not supply this application's statement/circuit or prove its embedding fit.
  Source: [official LaZer repository](https://github.com/lazer-crypto/lazer).
- **ISW21 lattice zkSNARK** is a possible R1CS experiment, not an accepted
  backend. The paper explicitly uses a designated-verifier preprocessing
  model; the upstream implementation identifies itself as a research
  proof-of-concept not intended for critical/production use. The local smoke
  run passed only its synthetic R1CS example. Before considering integration,
  test the exact fixed application relation, verifier-key handling, and
  canonical serialized proof size. Sources: [ISW21 paper](https://eprint.iacr.org/2021/977),
  [upstream implementation](https://github.com/lattice-based-zkSNARKs/lattice-zksnark).
- **LNP22** has a paper-level construction for short-vector linear relations
  and norm/range proof composition, but the pinned Go verifier's local
  regression demonstrates acceptance of a malformed range proof with missing
  bit subproofs. Re-ran the exact dependency assessment test on the current
  worktree (`go test -count=1 -run
  TestPinnedLNP22RangeVerifierAcceptsMissingRangeSubproofs -v`); it passed by
  reproducing the acceptance. The full probe suite also passed (`go test
  -count=1 ./...`), and `go vet ./...` returned clean; these test/vet passes do
  **not** clear the security defect. The current range API therefore remains
  disqualified unless corrected, pinned, and independently reviewed. Sources:
  [LNP22 paper](https://eprint.iacr.org/2022/284),
  [upstream Go implementation](https://github.com/KarpelesLab/lnp22).
- **Selection decision:** no candidate currently satisfies all gates on this
  machine. Do not wire any into the video API. The next meaningful candidate
  experiment is a fixed, verifier-pinned relation on an AVX-512-capable runner
  (or a separately audited implementation): public inputs must include the
  protocol/relation version, payload commitment, canonical video commitment,
  session and codec-policy hash; witness constraints and exact canonical
  serialization must be written before measuring embedding capacity. A smoke
  example, research-paper proof-size estimate, or signature is not a substitute.

### Public API fail-closed regression (2026-09-28)

- Added `t_public_apis_fail_closed_for_unreviewed_lattice_zkp` to the custom
  SIS-prototype test runner. It passes dummy existing files to public `embed()`
  and `verify()` and confirms both reject `lattice_zkp` before video parsing.
- Added a second fail-closed regression for `verify_near_blind()`: after the
  signed manifest, file hash, and position metadata are checked, a manifest
  declaring the research SIS proof is rejected before constructing the H.264
  parser. The first run failed as intended because parsing happened first;
  after moving the existing rejection guard earlier, the test passed.
- Registered this custom test module as Phase 28 in `src/runtest/run_all.py`.
  Invoking the phase through the standard runner returned `(7, 0, 0, 0)`.
- `py_compile` passes for both changed Python files, Ruff passes for the test
  module, F checks pass for `run_all.py` and `verifier_blind.py`, and
  `git diff --check` passes. This is a fail-closed behavior/performance guard,
  not proof-system validation or video-only ZKP completion.
- Attempted existing Phase 6 (`test_phase6_near_blind_manifest.py`) as a
  compatibility regression. During its real embed/verify case, Python RSS
  reached ~2.92 GiB and host free RAM fell to ~1.13 GiB while memory use was
  still increasing. I interrupted the test to protect the host; this attempt
  is **incomplete**, not a pass or code failure. Free RAM rose to ~4.04 GiB
  afterward. A bounded-memory or cached fixture is needed before safely
  rerunning that integration case on this machine.

### SIS prototype application-statement audit (2026-09-28)

- Direct inspection of `src/lattice_pq.py::LatticeZkProof.create/verify` and a
  new characterization test found that the proof's internal statement is
  prover-selected, not verifier-pinned. For message `m`, the prover chooses a
  32-byte key `k`, derives a ternary vector `x`, computes `A_m`, then sets
  `t = A_m x mod q`. The serialized proof contains `t`; `verify(m)` reads that
  same `t` from the proof and checks the Fiat-Shamir transcript. It accepts no
  expected statement, trusted witness/public key, payload opening, session,
  video commitment, or relation-registry entry as an input to this check.
- Reproduced by creating two proofs for the same message using arbitrary local
  keys `A*32` and `B*32`: both `verify(message)` calls returned `True`, their
  message hashes matched, and their internal statements differed. The
  regression `t_sis_prototype_accepts_a_prover_selected_statement` now retains
  this observation; the custom research-prototype suite returned **8/8 pass**.
  This is expected behavior of the current prototype, not a cryptographic
  security pass. It demonstrates that acceptance does not establish an
  externally authorized fact about the message or a video.
- The verifier checks response coordinates against `B-W`, but it does not
  directly check that an extracted witness is ternary. The code comments
  already avoid that claim. A formal Fiat-Shamir, special-soundness, and
  zero-knowledge analysis of this implementation is still missing; do not
  infer those properties from the transcript test or call this an application
  ZKP. The proof is not enabled in public embed/verify APIs.
- The shipped `proof_backend="lattice"` remains ML-DSA-65 receipt
  authentication with the receipt in a sidecar and only its commitment in the
  video. A fresh run serialized the experimental `LatticeZkProof` object to
  **131,692 JSON bytes**, while `pack_lattice_reference` placed only a
  **71-byte / 568-bit** `[LQ1][length][33-byte message][32-byte receipt
  commitment]` blob in the carrier. The proof bytes are not recoverable from
  that video payload. This is not the target embedded ZKP. The next
  cryptographic gate is to select and review a protocol whose verifier consumes
  a registry-pinned, canonical application statement binding the payload/video
  relation before any carrier integration.

### Carrier-to-IDR lookup optimization (2026-09-28)

- In `src/core/pipeline.py`, `_extract_bits_direct` previously searched the
  descending IDR-offset list linearly for every selected block. It now uses
  `bisect_right` over ascending offsets, preserving the rule “greatest IDR
  offset not greater than this macroblock” while changing lookup cost from
  O(carriers × IDRs) to O(carriers × log(IDRs)).
- Regression: `py -3.12 -m pytest
  src/runtest/test_extract_bits_parser_reuse.py -q` → **12 passed**. The
  existing cross-IDR ordering test exercises the mapping behavior.
- A controlled Python microbenchmark used 86,232 synthetic carrier macroblock
  indices and 3,000 synthetic IDR offsets: the old linear lookup took 3.722 s;
  binary search took 0.032 s (115.5× for this isolated lookup). This is not an
  end-to-end video benchmark and must not be interpreted as a 115× pipeline
  improvement. The measured full blind extraction remains far from realtime.
- `git diff --check` passes. Ruff still reports `BLE001` at the pre-existing
  broad exception handler in `src/core/pipeline.py`; this optimization did not
  change that handler or expand scope to rewrite it.

### Bounded blind-carrier analysis profile (2026-09-28)

- Profiled `derive_blind_positions_operating_contract` with `cProfile` on the
  first 10 frames copied from the real 3,000-frame Coastguard stego artifact
  (`FFmpeg 8.0.1`, 352×288, 331,482-byte sample, SHA-256
  `5bc7bef018fdf611669f789b68feab94b0ba5aa0fb2a7dbb6858071402dfb491`). The
  command requested 512 stable, patchability-checked carriers and returned
  all 512. The 93.463-second cProfile duration is instrumented and is **not**
  reported as production throughput.
- Profile evidence: 149,125,583 calls total. `CAVLCSafetyFilter.get_safe_positions`
  consumed 75.148 s cumulative; its hot paths included 178,303 calls to
  `_verify_block_bit_length_invariance` (43.563 s), 92,421 patch-context
  validations (23.885 s), and 63,257 exact block-patchability checks (23.217
  s). `extract_all_idr_blocks` consumed 17.039 s. This identifies the
  all-carrier safety analysis—not IDR lookup or cryptographic verification—as
  the next optimization target.
- The native `zks_cavlc_direct` implementation only mutates/extracts bits from
  already-decoded coefficient arrays; it does not parse Annex-B H.264 or
  replace this Python safety-analysis path. Therefore it is not evidence of a
  usable native extraction fast path.
- Next optimization must specialize analysis for the stable blind-carrier
  contract while preserving the exact position ordering, patchability,
  canonical digest and embed/extract agreement. Do not weaken or bypass
  bit-length/round-trip checks to claim speed. Validate it with differential
  tests against the current full path and a real stego-video blind extraction.
- The generated 10-frame temporary input was removed after profiling; the
  original video artifact was not modified.

### Stable-carrier-only analysis implementation (2026-09-28)

- Added an explicit `stable_blind_only` analysis-cache profile and a
  `stable_carriers_only` safety-filter mode. For this profile the filter
  evaluates the same deterministic AC carrier used by blind extraction in
  each block, while retaining the existing source-codeword patchability check,
  exact CAVLC length check, modified-code forward-decode check, and bitstream
  parse requirements. General/full analysis keeps its previous behavior.
- The blind position derivation and embed/extract/segmented blind paths now use
  that profile. It no longer computes safety results for unrelated carrier
  coefficients and no longer repeats `_prune_patchable_positions` after the
  safety filter has already validated the stable positions. Stable metadata is
  tagged `blind-sync-stable-v1` / `stable-blind-v1`; its `raw_safe_bits` count
  is scoped to that profile and is not interchangeable with full-analysis
  capacity counts.
- Differential unit coverage checks that stable-only safe positions equal the
  stable-candidate subset of full safety results and that fewer candidate
  modification checks are performed. The test was registered as runner Phase
  29. Phases 21 and 29 pass (3/3 and 1/1), and the focused analysis/streaming/
  LNP22 suite passes **45/45**.
- Real H.264 blind-carrier integration: `py -3.12 -m pytest
  src/runtest/test_video_only_blind_sync_integration.py -q` → **3 passed in
  105.94 s**. It verifies exact payload recovery from the stego video, stable
  carrier agreement between cover and stego, direct-vs-analysis extraction,
  canonical digest agreement, and successful strict decode. This is a carrier
  channel test, not an application-ZKP proof.
- Re-profiled the same 10-frame real stego sample as above (352×288,
  331,482 bytes, SHA-256
  `5bc7bef018fdf611669f789b68feab94b0ba5aa0fb2a7dbb6858071402dfb491`),
  requesting the same 512 stable patchable carriers. cProfile total fell
  from 93.463 s to 37.952 s (59.4% lower under instrumentation); cumulative
  `get_safe_positions` fell from 75.148 s to 19.753 s (73.7% lower). Exact
  patchability validations fell from 63,257 to 29,829. `extract_all_idr_blocks`
  remained about 17.2 s, now the largest single remaining measured phase.
  These are same-input instrumented profiles, not real-time FPS measurements
  or p50/p95/p99; instrument overhead is material.
- `py_compile` passes. Focused Ruff `E4,E7,E9,F` reported only existing issues
  outside the new hunk: an assigned-but-unused exception variable in
  `src/core/stego.py` and semicolon statements in `src/runtest/run_all.py`.
  `git diff --check` passes. No unrelated lint cleanup was made.

### Goal continuation verification (2026-09-28)

- Re-read the active goal objective and checked the published compact E2E
  artifacts. The standalone verifier result is now present and parses as
  `valid: true` (`benchmark/results/lnp22_video_e2e_compact_20260928T1109.verify.json`);
  corrected the probe README, which still said this recheck was running.
- Fresh uncached LNP22 Go tests: `go test -count=1 ./...` → pass in 4.703 s.
  Focused Python probe/report regressions:
  `py -3.12 -m pytest src/runtest/test_lnp22_video_e2e.py
  src/runtest/test_lnp22_video_quality_report.py -q` → **44 passed in 6.64 s**.
- This verifies the current experimental proof transport and rejection tests,
  not the missing application relation. The embedded proof still establishes
  only knowledge of a provisioned short linear-relation witness; payload-
  commitment opening, approved encoder correctness, production registry
  integration, independent cryptographic review, and realtime throughput
  remain unachieved. The measured 3,000-frame run took 16,931.57 s and used
  3,664.95 MB peak process-tree RSS, so it is explicitly not realtime.

### Payload commitment contract regression (2026-09-28)

- Added a fixed Python `hashlib` golden vector for the existing versioned
  SHA3-256 payload-commitment preimage and checked that the canonical public
  statement schema/serialization omits the payload and opening in common
  textual encodings.
- `py -3.12 src/runtest/test_video_zkp_contract.py` → **8/8 passed**;
  `py -3.12 -m ruff check src/runtest/test_video_zkp_contract.py` passed;
  `py_compile` passed for the test and statement-contract module; focused
  `git diff --check` passed.
- This is a Python reference-vector and schema regression only. There is no
  independent lattice-circuit implementation/fixture yet, so this does not
  demonstrate that a ZK circuit computes the same commitment or proves
  knowledge of its opening. The payload-length bound and canonical witness
  encoding also remain to be specified before circuit integration.
- Read-only Python review independently recomputed the digest and passed the
  assertions as scoped. It also confirmed these checks do not establish
  end-to-end payload privacy or witness privacy; those remain separate gates.

### Lattice backend capability recheck (2026-09-28)

- Source inspection of the pinned Go dependency (`github.com/KarpelesLab/lnp22`
  v0.1.1) confirms the current video probe calls `nizk.ProveLinear` /
  `nizk.VerifyLinear` for knowledge of a short vector satisfying `A·s = t`
  over its polynomial ring; this is not the module's only API (`tworing` is
  separately assessed below). The probe's SHA3 operation hashes the public
  context and derives an
  invertible row transformation; it does not place SHA3(payload, opening) in
  the proved relation. This backend cannot be represented as the required
  payload-hash-preimage proof without changing the commitment/relation design.
- The LaBRADOR paper demonstrates lattice-based proofs for R1CS and reports
  concrete sizes of 47–58 KB for its stated range of example constraints
  ([paper](https://eprint.iacr.org/2022/1341)). That is protocol evidence, not
  proof that this repository has a usable implementation of the required
  relation. The current [lattirust LaBRADOR implementation](https://github.com/lattirust/labrador)
  README says reductions from binary and ring R1CS are in progress; the
  [Lazarus framework](https://github.com/lattice-complete/Lazarus) labels
  binary-R1CS frontend work as a roadmap item and warns not to use the framework
  in production. The local LaZer candidate additionally remains unavailable on
  this host because the required AVX-512F instruction set is absent.
- No inspected candidate therefore currently supplies a locally runnable,
  independently reviewed R1CS lattice backend for the payload commitment.
  Do not wire an unrelated linear-relation proof into the verifier as a
  substitute. The next cryptographic decision is whether to (a) obtain a
  supported reviewed R1CS-capable backend for the existing SHA3 commitment, or
  (b) formally redesign the commitment as a lattice-native linear commitment
  and analyze its hiding, binding, canonical message encoding and parameters.
  Until that decision is supported by an executable backend and security
  analysis, selecting a fixed maximum payload size would be arbitrary; the
  present LNP22 default dimensions do not by themselves define a safe payload
  capacity.
- A new candidate for option (b) is present in the pinned LNP22 dependency's
  `commitment/bdlop.go`: it implements a BDLOP linear commitment whose message
  slots are polynomial vectors. This is only a candidate interface, not an
  accepted design. Its opening uses Gaussian randomness, while the current
  NIZK API proves witnesses under an infinity-norm bound; a valid composed
  relation must bind the message encoding and commitment equations and prove
  the opening lies within analyzed bounds. The module's helper `Verify` checks
  an opening when supplied—it is not itself a zero-knowledge proof. No code in
  the video pipeline uses this commitment yet.

#### BDLOP-to-linear-relation feasibility (source audit, 2026-09-28)

For the pinned BDLOP interface, the opening equations can be written as one
public linear relation over the same polynomial ring. With commitment key
`(B0, Bm)`, commitment `C=(T0,Tm)`, opening `(r,m)`, and identity matrix `I`:

```text
        [ B0      0 ] [ r ]   [ T0 ]
        [ Bm      I ] [ m ] = [ Tm ]       (mod q)
```

Here `T0=B0*r` and `Tm=Bm*r+m`; thus a *sound and properly parameterized*
short-witness proof for this full matrix could establish knowledge of an
opening. This is a design equation, not an implementation or security result.
The byte-to-polynomial map must be injective and versioned (including payload
length, padding, endianness and domain tag), and the commitment key must be
verifier-pinned. The public statement must include both commitment components
and all key/parameter identifiers.

The current LNP22 defaults cannot prove this opening as-is: BDLOP defaults use
`mu=3`, `lambda=3`, `ell=4` (ten randomness polynomials and four message
polynomials), while `nizk.DefaultParams()` uses `K=4`, `L=5`, `Beta=1`; the
combined equation above needs seven rows and fourteen witness polynomials, and
byte-valued message coefficients exceed the default witness bound. BDLOP's
Gaussian opening randomness also needs a rigorously selected tail bound. The
existing `VerifyRange` implementation is disqualified by the missing-subproof
acceptance reproduced below, so it cannot be used to impose canonical byte or
opening bounds. Any custom parameters, rejection distribution and proof
composition therefore require a fresh cryptographic analysis and independent
review; do not infer security from the default config or passing linear tests.

The pinned ISW21 source exposes generator/prover/verifier templates that take
an arbitrary libsnark R1CS and its primary/auxiliary inputs. Its vendored
libsnark provides SHA-256 compression and fixed-block gadgets, not a ready-made
arbitrary-length SHA3-256 payload-commitment circuit. A standard SHA-256
preimage circuit would still need correctly constrained block chaining,
padding, message length and byte encoding. This makes a *new SHA-256
payload-commitment version* a possible circuit experiment, but not a drop-in
proof of the existing SHA3-256 commitment. The bundled executable still
constructs only libsnark's synthetic example; the upstream proof object has no
video-format serializer, and verification uses a secret designated-verifier
key. The Linux smoke run does not test any application circuit or artifact
transport. Required next gates are therefore: build a fixed payload-opening
circuit with canonical public/private inputs, run positive and negative proofs
through ISW21, serialize and independently decode the proof, measure actual
proof size against carrier capacity, and review the designated-verifier key
and protocol assumptions. Until those pass, neither BDLOP+LNP22 nor ISW21 is an
accepted backend.

The ISW21 paper reports a proof just over 16 KB for its stated NP relation size
of `2^20` ([paper abstract](https://eprint.iacr.org/2021/977)); this is a
protocol result, **not** a serialized proof measured from this repository's
application. For scale, the recorded 3,000-frame H.264 transport run exposed
86,232 carrier positions (at most 86,232 raw bits, before framing). A >16,000-
byte proof would need >128,000 carrier bits, at least 1.49x that run's raw
capacity even before the LNPF header, context and error-correction overhead.
Therefore the existing 3,000-frame fixture is already too small for that
paper-reported proof scale; a proof-sized ISW21 circuit must measure actual
serialization and capacity on longer video before the candidate can pass the
embedding gate.

### Pinned LNP22 range-verifier defect reproduced (2026-09-28)

- Added `benchmark/lnp22_context_probe/lnp22_dependency_assessment_test.go` as
  a dependency assessment guard, not as desired product behavior. With the
  pinned `github.com/KarpelesLab/lnp22` v0.1.1, the test constructs a valid
  linear proof for a witness coefficient `2` under the backend's bound
  `Beta=2`, while claiming the stricter range `[-1,1]`. The dependency's own
  `ProveRange` rejects that witness, but a forged `RangeProof` that omits every
  bit subproof and supplies only correctly shaped zero reconstruction data is
  accepted by `VerifyRange`.
- Reproduced against the actual imported module with
  `go test -count=1 -run TestPinnedLNP22RangeVerifierAcceptsMissingRangeSubproofs -v`
  → **PASS (the defect reproduced)**. The complete probe suite also passes
  (`go test -count=1 ./...`), and `go vet ./...` reports no issues. The passing
  test means the assertion of this known defect holds; it is **not** a security
  pass for LNP22.
- A read-only Go code review independently confirmed the test's witness/range
  construction and verifier-path analysis; the focused reproduction also
  passed ten consecutive runs. This is implementation review of the regression
  test, not an independent cryptographic audit of LNP22.
- This disqualifies the dependency's current range-proof API from any payload
  byte/range argument unless the verifier implementation is fixed upstream,
  independently reviewed and pinned at a corrected revision. It strengthens
  the prior finding that BDLOP is only a candidate: do not build the payload
  commitment prototype on top of this range API or infer byte canonicality
  from `VerifyRange`. The standalone linear-relation probe remains explicitly
  experimental and does not inherit a security claim from these tests.

### ISW21 R1CS lattice zkSNARK smoke evaluation (2026-09-28)

- Evaluated the upstream `lattice-based-zkSNARKs/lattice-zksnark` repository at
  commit `48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e`, entirely inside Ubuntu
  24.04 Docker to avoid Windows checkout limitations in its older nested
  submodules. Upstream CMake configured and built the project successfully
  with GCC 13.3, CMake 3.28.3, `WITH_PROCPS=OFF`, and `WITH_SUPERCOP=OFF`.
- Ran the upstream `r1cs_lattice_snark_prime19_test 10000 100` example. It
  generated its sample R1CS, executed setup/proving/verification and returned
  `The verification result is: PASS`. The retained re-run took 14.75 s wall
  time, 14.35 s user CPU, and 429,856 KiB maximum RSS. The verifier portion
  reported approximately 0.0006 s. Output is retained in
  `benchmark/results/isw21_lattice_zksnark_smoke_20260928.txt` (SHA-256
  `f7578e61a96a3ff318d41e7a66a2b546edcb547a001e2073adfbd9eb955f000c`).
- This establishes that this research implementation builds and its bundled
  synthetic R1CS example accepts on the available Linux container; it does
  **not** establish a payload-commitment circuit, a serialized proof size,
  blind extraction or video embedding, or a security review. Its README
  explicitly labels the code a proof-of-concept not intended for production,
  and the scheme is designated-verifier. It is therefore only a viable
  research candidate for assessing whether the existing commitment can be
  expressed as R1CS, not an accepted production backend or goal completion.

### LaBRADOR backend feasibility check (2026-09-29)

- The LaBRADOR paper reports a lattice-based R1CS argument at 128-bit
  security with a 58 KB proof for a 2^20-constraint instance. This is a
  published parameter/result, not a measurement on this machine or on the
  video's application circuit; at face value it is below the previous
  131,710-byte patchability-only request, but gives less than 2.3x size headroom
  before protocol framing and any increase in circuit size.
- Evaluated the original `lattice-dogs/labrador` source at commit
  `8b6626b26afd4c0162ddd089759d21d3d51bfbdf`. The README says this
  implementation requires AVX-512 and describes its bundled main test as a
  random polynomial commitment/evaluation proof, not a user-defined R1CS
  application circuit. The current Docker host exposes no AVX-512 flags; the
  actual `make -B test_greyhound` build failed with repeated AVX-512 intrinsic
  `target specific option mismatch` errors. Captured output is
  `benchmark/results/labrador_avx512_build_20260929.log`.
- Also checked the Rust port at `lattirust/labrador` commit
  `024c48e49025765ef3a7c08889b2d2fc61de0612`. Its README explicitly says only
  core LaBRADOR is implemented and binary/ring R1CS reductions are in progress;
  its ring-R1CS module is commented out in `src/lib.rs`. The workspace exposes
  a small binary-R1CS reduction/test. Plain `cargo test` initially stopped
  before target compilation because a git SSH submodule fetch failed, then the
  dependency build script could not find SageMath (`sage`) after rewriting
  that dependency to HTTPS. To inspect the test path, a temporary `/bin/sh`
  shim was used only for that Sage path probe; it is **not** SageMath and must
  not be treated as a valid security-estimator environment. Under this shim,
  `binary_r1cs::test::test_completeness` failed twice: the test generates and
  first validates a satisfied input R1CS, then the reduction returns an output
  witness that fails the reduced relation's constraints. The failure happens
  before proof verification. Full `cargo test` under the shim reported 1 pass
  and 3 failures: this binary-R1CS completeness failure, plus two unrelated
  core tests that failed while invoking the unavailable Sage estimator. Exact
  logs are `benchmark/results/lattirust_labrador_cargo_test_20260929.log`,
  `benchmark/results/lattirust_labrador_cargo_test_shim_20260929.log`, and
  `benchmark/results/lattirust_labrador_binary_r1cs_completeness_20260929.log`.
  The port labels its version `0.0.1-alpha`; the repeated reduction failure is
  a concrete correctness blocker for this code revision, not a claim that the
  LaBRADOR paper protocol itself is unsound.
- Preliminary source diagnosis of the binary-R1CS failure: the test packs 256
  scalar variables into `n_pr=4` ring elements of degree `d=64`. The failing
  output standard constraints 1..12 correspond exactly to the 12
  conjugation constraints added for `a`, `b`, and `c` after the first `t`
  constraint. `binary_r1cs/util.rs::reduce` loops over `0..n_pr` and uses
  `basis_vector(i, n_pr)` / `basis_vector(n_pr-i, n_pr)` on vectors of ring
  elements, while the intended relation comment describes coefficient
  indices of the degree-64 ring automorphism. This is a strong index/modeling
  mismatch candidate for those 12 failures. It is not yet a validated fix:
  dozens of constant-coefficient constraints also fail, so even correcting
  the conjugation constraints alone may not restore completeness. Keep this
  port rejected until a principled reduction repair passes the original
  completeness/soundness tests with a real SageMath environment and receives
  an independent cryptographic review.
- Related soundness-review item from the same source: the conjugation loop
  adds constraints for `a`, `b`, and `c`, but not for `w`, although the reduced
  witness also contains `w_tilde = sigma(w)` and the later constant quadratic
  constraints use the pair `(w, w_tilde)`. The current test does not establish
  whether those other equations imply the missing relation. Treat this as a
  potentially underconstrained witness binding that must be formally checked;
  do not repair by adding ad hoc constraints and assume soundness.
- Decision: LaBRADOR is a stronger *research candidate* than the ISW21 smoke
  implementation on paper, but neither code path is currently a verified,
  runnable prover/verifier for this system on the available hardware. Do not
  adopt either as a production backend yet. A useful next gate is either
  obtain an AVX-512 build host for the original code, or repair and review the
  Rust reduction, install its pinned Sage/dependency stack and pass its tests,
  then instantiate the exact reviewed video/payload relation and measure the
  real serialized proof before any embed integration.
- Independent Linux filesystem rebuild and smoke rerun on the same pinned
  commit (2026-09-28): recursive checkout/build was run inside Ubuntu 24.04
  Docker because a nested upstream filename containing `:` cannot be checked
  out on Windows NTFS. CMake completed and all listed test executables built.
  The repeated `r1cs_lattice_snark_prime19_test 10000 100` again returned
  `PASS` and process exit status 0; measured 14.80 s wall, 14.32 s user CPU,
  429,976 KiB peak RSS. Exact console/build evidence is retained in
  `benchmark/results/isw21_linux_build_verify_20260928.log` and
  `benchmark/results/isw21_linux_smoke_exitcheck_20260928.log`. These are
  repeatability/build-feasibility observations for the upstream synthetic
  example only, not application proof benchmarks, proof-size measurements, or
  evidence that the video pipeline meets its acceptance criteria.
- Source-level artifact audit of that exact smoke-test path: at the pinned
  source, `r1cs_lattice_snark_proof` in
  `/tmp/isw21/lwe/snark/r1cs_lattice_snark_common.hpp` wraps one ciphertext;
  the test calls `prove`, passes the in-memory object directly to `verify`,
  and discards it. No proof serialization/deserialization or standalone proof
  artifact API was found in the upstream `lwe/snark` and container sources.
  For the test's `B19C20` parameters (`n=2045`, `pt_dim=32`, `tau=4`,
  `q=2^108`), its ciphertext contains two extension vectors of lengths 2045
  and 36; each extension has two ring coefficients. A hypothetical canonical
  fixed-width encoding using 14 bytes per 108-bit coefficient would therefore
  be 4,162 × 14 = 58,268 bytes before framing. This is an encoding estimate,
  **not a measured/standardized proof size**, and the upstream verifier still
  requires a secret key, so it is designated-verifier rather than a public
  standalone verifier artifact.
- The estimate is below the 131,710-byte request previously confirmed by the
  *patchability-only* Coastguard scan for a different 131,694-byte payload
  plus 16 bytes framing. This arithmetic alone does not prove that ISW21 proof
  fits: no serializer exists, the scan did not validate quality or extraction,
  the proof came from a synthetic 10,000-constraint circuit, and the real
  application relation can be much larger. Next candidate gate requires a
  reviewed canonical serializer/deserializer and a fixed application circuit;
  until then ISW21 has not passed the video-carrier integration gate.
- Next meaningful gate: implement a tiny, fixed relation circuit in an
  isolated experiment (including the exact public statement and witness
  encoding), measure the actual serialized proof and setup/prover/verifier
  resources, and have the cryptographic assumptions and designated-verifier
  model reviewed. Do not infer SHA3 support/circuit fit from the generic R1CS
  smoke test or replace the relation with an unrelated example.

#### ISW21 proof representation / carrier-size estimate (not serialized evidence)

- Source inspection of `r1cs_lattice_snark_common.hpp` and the `B19C20`
  parameters shows the proof object contains one LWE ciphertext response:
  `a_vec` has 2,045 ring elements; `c_vec` has 36 (`pt_dim=32`, `tau=4`).
  Each residue is modulo `q = 2^108`, for 2,081 residues total.
- A canonical fixed-width bit-packed representation of just those residues
  would require `ceil(2,081 * 108 / 8) = 28,094` bytes. Padding each residue
  to 14 bytes would be 29,134 bytes; storing each in its in-memory 16-byte
  `uint128_t` slot would occupy 33,296 bytes. These are derived representation
  sizes, **not** an upstream serialization or a measured transport proof.
  Upstream's smoke test does not serialize or report proof bytes, and all
  figures exclude statement, parameter/version identifiers, framing and
  extraction metadata.
- The bit-packed estimate is below the previously measured 1,053,680
  patchable carrier bits on the 3,000-frame Coastguard fixture, but that scan
  only established a targeted patchability count for a different 131,694-byte
  experimental payload; it did not embed this candidate proof or validate
  quality, blind extraction or verification from a resulting video. Therefore
  this arithmetic is only a prioritization signal for a serialization/E2E
  experiment, not evidence that the candidate fits the video or satisfies the
  carrier policy.

### ISW21 application-circuit feasibility probe (2026-09-29)

- Inspected the pinned ISW21 source in the existing Ubuntu 24.04 audit
  container (48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e). Its R1CS path can in
  principle express a hash-preimage relation, and the vendored libsnark source
  includes SHA-256 compression gadgets. The current application contract uses
  SHA3-256, however; the available gadget is not a SHA3 gadget, so this does
  not implement the current payload-commitment relation.
- Built the dependency's existing target with
  make -j2 test_sha256_gadget and executed
  ./depends/libsnark/libsnark/test_sha256_gadget in that container. The
  existing two-to-one SHA-256 compression gadget reported 27,280 R1CS
  constraints and its fixed test vector passed. This is a dependency fixture
  in its default libsnark field, not the ISW21 lattice proof over
  Fp2_b19_pp, and not a complete padded SHA-256 preimage circuit. Captured
  output: benchmark/results/isw21_sha256_gadget_20260929.txt (SHA-256
  C2F875D62F666B41D2580C5B1B89C5828740A2735E3377169387229F81D57844).
- This result makes a fixed SHA-256 commitment relation a plausible circuit
  experiment, but switching away from the current SHA3 commitment would
  require an explicit statement/protocol version change and security review.
  Alternatively, an exact SHA3/Keccak gadget must be implemented and tested.
  Neither route has yet produced an application circuit, lattice proof,
  serialized verifier artifact, or video-embedded proof. ISW21's own README
  still labels the code a research proof-of-concept and not production-ready;
  its designated-verifier key model also remains a protocol choice to review.
- Drafted `benchmark/isw21_application_probe/payload_sha256_r1cs.cpp` for a
  fixed 96-byte SHA-256 commitment preimage. This is not a working circuit:
  compilation first exposed two vendored libsnark incompatibilities
  (`FieldT = 0` with ISW21's explicit extension-field conversion, then
  `.as_ulong()` in the SHA majority witness). Narrow compatibility patches
  address those two compile sites, but compilation then fails in the generic
  bit-packing path because `Extension<Fp2_b19>` lacks `FieldT::num_limbs` and
  `.as_bigint()`. An attempted extension adapter is not valid generically since
  ISW21 also instantiates `Extension` with a custom `Field` that lacks the
  underlying integer API; the adapter was reverted. The final compile-only run
  exited 1; raw output is
  `benchmark/results/isw21_payload_sha256_r1cs_compile_20260929_raw.txt`
  (SHA-256 `C6187B6D6DF188A1FFEDC3BB1DA17B8DA5B9A70A991090E44B45F882F7E3ED8C`).
  Reproduction/status is recorded in
  `benchmark/isw21_application_probe/README.md`. No circuit executable,
  assignment test, proof, verifier result, or resource benchmark was produced.
- Code inspection then exposed a correctness issue beyond the compile error:
  this ISW21 configuration's base field is `p = 2^19 - 1 = 524287`
  (`B19Fp2ParamsBase::p_int`), while the generic SHA-256 gadgets pack 32-bit
  words using `pb_packing_sum`/`packing_gadget`/`lastbits_gadget`. Packed
  powers of two are scalar multiples of the field identity, so they remain in
  the prime subfield of size `p` even though the ambient type is Fp². This
  encoding is not injective for 32-bit words: the all-ones 19-bit integer
  `p` and zero both map to zero (`2^19 = 1 mod p`). Therefore merely adding
  `as_bigint`/`num_limbs` API compatibility would not make the gadget's
  32-bit decomposition sound. The vendored generic SHA-256 gadget is
  disqualified for this field/relation unless replaced by a separately
  reviewed bit-only circuit that expresses each SHA word operation via
  boolean/carry constraints, or the backend changes to a sufficiently large
  field with reviewed compatible gadgets. Neither path has been built or
  tested; the reasoning and source anchors are in the probe README.
- This evidence changes the next gate: do not continue layering ad hoc patches
  onto the generic upstream field abstraction. First implement or select a
  reviewed SHA-256 relation that avoids packing 32-bit words into this small
  characteristic field (or prove that a replacement lattice backend provides
  the required sound field/gadget semantics). Then test exact satisfying and
  unsatisfying payload/opening statements before attempting lattice
  proving/verification, serialization, and resource measurement. The
  27,280-constraint hash fixture is not evidence of application circuit fit or
  acceptable security.

### CAVLC VLC-prefix parser optimization probe (2026-09-28)

- A `cProfile` run of the stable-blind parser on the first 10 Coastguard CIF
  frames recorded 59,988,703 calls in 38.787 s under profiler overhead. The
  old `decode_vlc` prefix scan accounted for 23.572 s cumulative across
  117,138 calls; `get_safe_positions` accounted for another 20.601 s. This
  identified VLC prefix matching as a real hotspot, but the profiled time is
  not a wall-clock performance claim.
- `decode_vlc` now pre-indexes proper prefixes for built-in CAVLC tables, which
  are frozen after construction to prevent stale cache entries. Caller-owned
  mutable tables are indexed afresh and are not cached. Regression coverage
  checks custom-table mutation, cache reuse, and rejection of mutation through
  the built-in table getter. The related CAVLC/parser suite passed **68 tests**
  on Python 3.12.10; the focused cache tests also passed in independent review.
- An alternating legacy-scan/current-parser experiment ran six stable-blind
  analyses of the same 10-frame file (62,592 coefficient blocks and 1,422 safe
  positions each). The fixture SHA-256 is
  `FC86406B8DAB0AD54F720712D5EBC365009E285E72A140D07C0E5E39DE32E084`;
  machine: Windows 11, Intel Core i7-12700H, Python 3.12.10. Legacy times were
  13.828/18.301/14.736 s (median 14.736 s); indexed times were
  14.021/14.694/13.481 s (median 14.021 s), a 4.9% median difference. The
  ranges overlap and the sample is small, so this is **inconclusive exploratory
  evidence**, not a demonstrated pipeline speedup. A controlled benchmark with
  more repetitions and CPU/process-load monitoring is still required.
- This parser change does not implement or accelerate a lattice proof, does
  not change the ZK relation or carrier capacity, and establishes neither
  realtime performance nor end-to-end proof embedding.

### Context-binding helper audit (2026-09-28)

`src/video_zkp_contract.py::verify_video_zkp_context_binding` now composes
three checks for a future verifier integration: (1) canonical statement and
carrier-position digest match, (2) relation/policy/issuer-authenticated
registry pins and minimum epoch match, and (3) the canonicalized video digest
matches the statement. Carrier positions must be a finite sequence; the helper
snapshots them once and uses the same snapshot for both position hashing and
video hashing. This avoids accepting a one-shot iterator or hashing different
positions across the two checks.

The focused contract and context-relation scripts pass (9/9 and 5/5 tests,
respectively), and canonicalization/parser-reuse pytest coverage passes (4/4).
An independent Python code review found no issue in the new helper/test scope.
This helper is **not** a ZK verifier and is not yet called by a complete
video-only proof-verification pipeline. It does not derive/authenticate the
carrier list from a trusted blind extractor, check `cover_hash`, fetch and hash
registry artifacts, open the payload commitment, or verify the application
relation/proof. Passing these context checks alone proves none of those claims;
integration and independent review of the actual lattice proof backend remain
mandatory.

### LNP22 application-relation gap characterization (2026-09-28)

The compact LNP22 probe proof correctly rejects reuse under a *changed* context,
but that alone does not make payload fields part of the proved relation. A new
negative-scope/characterization test,
`TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening`, provisions one
fixed relation witness and successfully creates/verifies proofs under two
distinct `payload_commitment` values. Run it with:

```powershell
Set-Location benchmark/lnp22_context_probe
go test -count=1 -run 'TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening|TestCompactFixedRelationProofBindsCanonicalContext' -v
```

The companion context-mutation test confirms that a proof made for context A
still fails against context B. Therefore the accurate interpretation is:
LNP22 binds the chosen canonical context to a proof of knowledge for the
pre-provisioned short linear-relation witness, while the current relation does
not prove that the witness opens `payload_commitment` to the embedded payload.
This test is not a break of the proof system; it records that the application
claim is outside the relation. The demo payload remains public and no
payload-privacy claim is supported. An accepted backend must place the actual
application witness and its commitment-opening/predicate relation inside a
reviewed proof relation, with negative tests that reject invalid openings.

### Pinned LNP22 two-ring verifier disqualified (2026-09-28)

The pinned `github.com/KarpelesLab/lnp22` v0.1.1 module contains a `tworing`
package in addition to the linear `nizk` path previously evaluated. Source
review found its Fiat--Shamir transcript hashes the statement, `W`, and `Wq`,
but omits `Wy`; `Verify` nevertheless consumes `Wy` in the quadratic equation.
The verifier also does not enforce `Statement.Norm`; the prover-side response
norm calculation is discarded. These findings were checked against the
installed, checksum-pinned module and independently reviewed.

`benchmark/lnp22_context_probe/lnp22_dependency_assessment_test.go` now
reproduces a direct forgery at runtime: use the impossible quadratic statement
`B = 0`, `V = 1`; set `Z = 0`, `Wq = 0`; compute the challenge using the pinned
transcript format; and set `Wy = -c^2`. The verifier accepts this proof without
any witness. It also characterizes the ignored norm constraint. Reproduce all
three pinned-dependency defects with:

```powershell
Set-Location benchmark/lnp22_context_probe
go test -count=1 -run 'TestPinnedLNP22(RangeVerifierAcceptsMissingRangeSubproofs|TwoRingVerifierAcceptsWitnessOutsideNormBound|TwoRingVerifierAcceptsQuadraticForgeryFromUnhashedWy)$' -v
```

This is a concrete soundness failure in the experimental dependency, so both
`nizk.VerifyRange` and `tworing.Verify` are disqualified from the system's
security claim. The current video path uses `nizk.VerifyLinear`, so this
quadratic forgery does not retroactively invalidate that narrower linear
transport demonstration; the broader dependency remains unaudited, and the
linear proof still does not establish payload-commitment opening or an
application predicate. Do not switch the video path to `tworing` to address
that gap. A corrected upstream revision plus independent cryptographic review
is required before reconsideration.

**Current-worktree recheck (2026-09-29).** Re-ran the three dependency
assessment tests above on the pinned v0.1.1 module: all **3/3 reproduced**.
Also re-ran
`TestCompactFixedRelationProofBindsCanonicalContext` and
`TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening`: both passed.
The latter confirms that two distinct payload-commitment values can accompany
valid proofs for the same fixed relation witness; this is expected for the
probe because that commitment is only transcript context, not a proved
opening. Commands and output were executed in
`benchmark/lnp22_context_probe` with `go test -count=1`; these results
reconfirm a disqualified candidate and do not advance it toward acceptance.

### Full regression-suite resource abort (2026-09-29)

Re-ran `py -3.12 -m src.lazer_backend`: Linux/x86-64 and Docker were visible,
but `avx512f_required` remained, so the pinned LaZer demo cannot run here. Then
started `py -3.12 src/runtest/run_all.py`; the runner reached
`test_phase5_extract_verify.py`, where the child process's working set grew to
5.76 GiB and host free RAM fell to 1.40 GiB. I sent Ctrl+C at that safety
threshold. The runner produced no phase summary/exit status, so this is an
incomplete run, not a pass. Available RAM recovered to 6.71 GiB afterward and
no new `test_p5_*` video outputs remained. Full process samples and limits are
in `benchmark/results/full_suite_resource_abort_20260929.md`. Next isolate
Phase 5's subtests and instrument per-stage memory/cache growth under a strict
cap before attempting another full-suite run; do not rerun it unbounded on
this host. Separately, the bounded quick subset (`py -3.12 -u
src/runtest/run_all.py --quick`) completed twice at 23/23 with exit 0; the
captured rerun is `benchmark/results/quick_suite_20260929.txt` (SHA-256
`90A9D20D04D804E854D2C0B4FCE5B652B5B17C67DEC6A5F23A535B83A7AB4BCC`). This
covers the legacy Groth16 utility, H.264 parser and safety/embed phases only;
it is not lattice-ZKP, blind-extraction, or full-suite acceptance.

### Isolated Phase 5 candidate-analysis profile (2026-09-29)

Profiled the existing smaller candidate `akiyo_cif_q22_g1.h264` (4,074,416
bytes), without changing asset order or runtime code. In one Python 3.12 run,
NAL parsing took 2.35 s/40 MiB RSS; IDR extraction reached 1.764 GiB RSS after
78.84 s (995,670 macroblock records, 300 IDR frames and 1,570,116 entries in
each of two offset maps); complete safety enumeration reached 2.391 GiB RSS at
340.69 s cumulative, producing 1,636,667 candidate positions. Pruning to 424
patchable positions finished at 345.04 s cumulative. These are stage-boundary
readings from one exploratory run, not peak-memory guarantees or repeated
performance results.

This shows that choosing the smaller clip first does not solve resource cost:
exhaustive safety enumeration dominates the measured run. Any optimization
must bound/stream carrier analysis while preserving exact patchability and
forward-decode checks, deterministic order, and fail-closed behavior when
capacity is exhausted. Differentially test it against exhaustive analysis;
total-capacity benchmark paths must remain exhaustive. Evidence and method are
recorded in `benchmark/results/phase5_staged_rss_akiyo_20260929.md`.

Reviewing the proposed early-stop optimization exposed a correctness hazard:
`get_safe_positions()` returns `sort_blocks_interleaved(...)` after separately
collecting ordinary and trailing-one sign carriers. Source-order truncation is
not the prefix of that frame-interleaved order. A synthetic runtime check
confirmed the first two positions differ. Do not add a naive `max_positions`
break. An optimization must lazily produce the exact exhaustive-order prefix
including T1 sign carriers, or add a versioned order profile used consistently
by embedder, blind extractor and verifier and cover profile/replay incompatibility
with negative tests. Runtime acceptance remains open.

### LaZer host compatibility recheck (2026-09-29)

Reran preflight and the guarded demo command. Docker is available; its Linux
x86-64 guest exposes AES/AVX2 but not AVX-512F. Preflight denies execution and
`--run` raises before launching the image; no LaZer proof was generated. The
upstream requirements still specify AVX-512 for LaZer and the original
Labrador implementation; Lattirust's R1CS reduction remains unfinished and
the project labels itself unaudited research code. The issue is not Docker
configuration, and the host gate will not be weakened. Full command output,
upstream links and the accurate scope of this conclusion are in
`benchmark/results/lazer_host_recheck_20260929.md`. Even an AVX-512 runner
would not supply the missing application relation, proof serialization or
video-only verifier.

### Public lattice-ZKP gate regression (2026-09-29)

Ran `py -3.12 -u src/runtest/test_lattice_zkp.py` twice; both runs exited 0
with **8/8** custom tests passing. The captured repeat is
`benchmark/results/lattice_zkp_fail_closed_20260929.txt`. Importantly, these
tests pass partly by confirming current limits: the SIS prototype accepts a
prover-selected statement (a characterized relation flaw), default `lattice`
means ML-DSA-65 attestation rather than a ZKP, and both public APIs reject the
experimental `lattice_zkp` backend. The blind-verifier test confirms a
research-only proof-system artifact is rejected before video parsing. These
are useful fail-closed guards; they are not ZKP functionality or system
acceptance. Current source therefore does not silently substitute a receipt
when `proof_backend="lattice_zkp"` is explicitly requested, but the default
public path still embeds a reference to a sidecar attestation and does not
meet the goal's in-video ZKP requirement.

### Statement-contract execution and integration audit (2026-09-29)

Ran `py -3.12 -u src/runtest/test_video_zkp_contract.py` twice; both runs
passed **9/9**, with the captured run at
`benchmark/results/video_zkp_statement_contract_20260929.txt`. These tests
cover canonical statement serialization, video/position hash helper behavior,
policy/relation registry pin checks, and mutation rejection. They test the
contract helpers in isolation, not a proof relation or end-to-end verifier.

Current-source call-site audit (`rg` over `src/*.py`) finds
`build_video_zkp_statement()` called from `embed()` only when an ML-DSA
`LatticeReceipt` and optional `zkp_payload_opening` are present. The composed
`verify_video_zkp_context_binding()` helper has no production call site in
`src`; calls occur only in tests. `verify()` instead unpacks the embedded
32-byte ML-DSA receipt reference and loads the signature receipt from
`<stego>.lattice.json`. Thus the contract's field and pin tests establish no
runtime proof verification, payload-commitment opening, registry resolution
inside the verifier, or blind-video-only operation. Keep this surface labeled
as a future statement contract until a reviewed proof backend consumes it and
the verifier derives all relevant inputs from the video and verifier trust
configuration.

### Additional lattice-ZK candidate review (2026-09-29)

Reviewed the AVX/SSE-capable `yarongvili1/latticezk` source/API as an
alternative to the AVX-512-gated LaZer path. It is not ISA-blocked, but is
rejected for integration at this stage: the demonstrated verifier is
constructed using proof-carried dimensions/matrices rather than a
project-pinned video/payload relation, and the upstream repository labels
itself experimental with tests covering only some CPU matrix operations. Its
demo uses `lambda=80`; the security guarantees of the cited interactive
prime-field protocol cannot be carried over automatically to the repository's
power-of-two/hash-challenge adaptation.

Its default 1.21M scalar proof matrices yield a derived 38.72M-bit estimate at
32 bits per scalar, versus 1,232 operating bits / 2,000 patchable bits in the
measured Akiyo clip. This is not a measured serialized size and Akiyo is not a
universal carrier bound. Full source/API assessment, calculations and primary
links are in
`benchmark/results/latticezk_candidate_assessment_20260929.md`. No candidate
code was cloned, built, or executed. Reconsider only with a verifier-pinned
application relation, independent security review and measured in-capacity
serialization.

### Broader lattice-ZK alternatives review (2026-09-29)

Searched additional current primary-source candidates. Jolt with its Akita
lattice PCS is the strongest future architecture found for verifier-pinned
general computation, but Jolt's current documentation explicitly says Akita
supports clear proofs only; its `akita` and `zk` features are mutually
exclusive, and BlindFold's ZK path applies to Dory. Akita is therefore not a
ZK backend in the current selected configuration. Upstream reports proof
sizes of 65-80 KB, compared with the measured Akiyo operating capacity of
1,232 bits; this is not a local measurement and Akiyo is not a universal
capacity bound. Akita has not received a formal production audit, and Jolt
describes itself as alpha.

The latest Lazarus repository roadmap still marks proof serialization and a
binary-R1CS front end pending; its migration notes defer `quadratic==2` and
say its SIS security estimator needs recalibration before a formal claim.
Lantern's available Sage implementation documents insecure built-in sampling,
no side-channel hardening and poor fit for large circuit satisfiability; the
repo's own LNP22 probes additionally expose the application-opening gap and a
separate two-ring soundness forgery. No code was fetched/built/run for these
new candidates. Detailed primary links and candidate disposition are in
`benchmark/results/lattice_zk_alternatives_assessment_20260929.md`.

Current search therefore finds no backend meeting the goal's relation, ZK,
security-review and carrier-size gates. The next qualifying candidate must
have a reviewed ZK-capable lattice commitment/proof path (not merely a
lattice PCS), executable circuit/relation binding the verifier-derived video
and payload data, reproducible proof serialization, and a measured fit in the
quality-validated carrier.

### Lazarus / LaBRADOR source recheck (2026-09-29)

The earlier Lazarus assessment predates a newer implementation state. Rechecked
the official repository at commit
[`4363e5151a25dac2e96885cd08c1bdfb7ac3c1af`](https://github.com/lattice-complete/Lazarus/tree/4363e5151a25dac2e96885cd08c1bdfb7ac3c1af).
This version contains a Rust LaBRADOR proof path over sparse linear/quadratic
ring constraints and a witness norm bound (`labrador/src/principal.rs`,
`composite.rs`). It may be investigated for the separately proposed linear
commitment statement-v4. It does not implement the current SHA3-preimage v3
relation: the pinned [migration map](https://github.com/lattice-complete/Lazarus/blob/4363e5151a25dac2e96885cd08c1bdfb7ac3c1af/docs/MIGRATION.md)
still lists the binary-R1CS/Dachshund frontend, `quadratic==2`, and full proof
serialization/entropy coding as unfinished.

At this commit, `PrincipalStatement.h` is the initial transcript hash, so an
application wrapper could derive it from canonical verifier-selected public
inputs. No such wrapper or relation exists yet. `CompositeProof` is currently
an in-memory object containing rounds and a `final_witness`; the code comments
describe that final witness as sent in the clear. This must be mapped to the
paper's ZK simulator and reviewed for this exact protocol before asserting
private-witness safety; the source shape alone is not sufficient to assess the
full construction. **Correction to an earlier assessment:** the underlying
[LaBRADOR paper](https://eprint.iacr.org/2022/1341.pdf) explicitly says it
disregards zero knowledge for its base proof system. It suggests composing the
base protocol with a linear-sized witness-masking shim to obtain zero
knowledge, but this project has not implemented or reviewed that shim. The
paper's knowledge-soundness result therefore does not make this Rust proof path
a ZKP; the clear `final_witness` field reinforces that this implementation
must not be treated as witness-private. A theorem-backed, implemented and
tested masking composition with a security review is a separate prerequisite;
absent that, this candidate fails the goal's ZK gate. The migration map also
says the Rust port is not byte-compatible with the C implementation, records
sampler/backend differences, and calls its root-Hermite MSIS estimate coarse
pending recalibration.

There is a concrete but unimplemented way to express a *linear-commitment
v4* payload relation through the `PrincipalStatement` surface: represent each
bit `b_i` by scalar witness polynomials `(u_i,v_i)` and require
`u_i+v_i=1` and `u_i^2+v_i^2=1`. Over the odd prime scalar field
`q=2^32-99`, these equations force `(u_i,v_i)` to be `(0,1)` or `(1,0)`;
commitment rows can then constrain `C=A_r*r+A_p*b`. Because the backend's
ring is `Z_q[X]/(X^64+1)`, an implementation must also constrain all
nonconstant coefficients of every scalar witness to zero (e.g. with
coefficient-isolating constant-term rows), or the scalar-field argument does
not automatically transfer to arbitrary ring elements. The verifier must
derive the matrices and constraints from the canonical, versioned statement.
This only shows a plausible constraint encoding. It does not establish
commitment hiding/binding, soundness of parameter choices, transcript
domain-separation, application-level ZK, acceptable proof size, or video
capacity; those remain explicit tests/review gates.

The source was inspected from an external shallow checkout pinned to the commit
above. The host has no local `rustc`/`cargo`, so the pinned workspace was tested
in `rustlang/rust:nightly-slim-2026-09-15`
(`sha256:66726eb549e867024ed4b890cb133e7304b52cc2f380d425b7ce210849970894`):
`cargo test -p labrador` completed with **35 passed, 0 failed** (24.22 s
compile; 2.02 s test runtime). The tests cover toy sparse-relation proof
rounds, a composite proof, and tamper rejection. They do not test the proposed
payload commitment, video context, blind extraction, full-proof serialization,
or zero-knowledge leakage of the final reduced witness. No proof-size or video
capacity result was measured.

#### Fixed-statement lattice-shaped relation probe (2026-09-29)

The temporary external test was extended to map a two-row q-ary linear form
`C=A*r+G*u` into LaBRADOR sparse constraints, alongside one-hot constraints
`u+v=1`, `u^2+v^2=1` and coefficient-pinning rows. With verifier-fixed
`C=(-12,-12)` and `betasq=7`, the valid `(r,u,v)=((0,0),1,0)` opening proves
and verifies. A false `(u,v)=(2,-1)` opening with `r=(-1,1)` has the same
commitment and bound, satisfies both linear commitment rows and the sum
equation, but fails the quadratic bit equation. Context-only and public-row
mutation checks reject the proof as well.

Crucially, this test exposed an explicit binding failure in its deliberately
tiny matrix: a second *valid* bit-0 opening `((1,-1),0,1)` also opens the same
`C` under the same bound and passes the principal verifier. Here `G=A*(1,-1)`;
these toy constants are intentionally insecure. This demonstrates relation
plumbing and catches a non-bit witness, but also proves this parameterization
cannot be a secure payload commitment. It is not evidence of hiding, binding,
application-level zero knowledge or acceptable security parameters. The probe
hash `h` covers its fixed-schema matrices, commitment, bound and context; it is
not a generic digest of arbitrary `PrincipalStatement` contents. The harness
is in the external temporary clone, not the project tree; the composite proof
serialization, `final_witness` privacy, H.264 embedding and carrier capacity
remain untested.

Actual command/result: `cargo test -p labrador --test
linear_commitment_probe` in the pinned Docker image above: **1 passed, 0
failed** (4.22 s test runtime). This advances only the backend relation-mapping
gate. It does not qualify LaBRADOR or this toy commitment as the system backend.

Disposition: retain Lazarus/LaBRADOR as a focused *research* candidate for a
linear statement-v4 only; do not integrate it or mark the system complete.
The probe's commitment fails binding, so the next gate is a concrete
commitment construction with independently analyzed parameters and explicit
hiding/binding arguments—not another toy matrix. Then require a verifier-built
canonical statement digest, theorem-to-code ZK review of the reduced final
witness, a canonical full-proof codec and measured proof size before
video-capacity work.

#### BDLOP bridge feasibility check (2026-09-29)

Inspected the pinned Go dependency source at
`github.com/KarpelesLab/lnp22@v0.1.1/commitment/bdlop.go` and compared it with
the pinned Lazarus LaBRADOR ring implementation. BDLOP's opening equations
have the required linear shape `T0=B0*r`, `Tm=Bm*r+m`, and its source exposes
uniform public key generation and Gaussian opening randomness. The underlying
[BDLOP paper](https://eprint.iacr.org/2016/997.pdf) supports computationally
hiding and binding instantiations under structured lattice assumptions, but
that result depends on concrete parameter choices; it does not validate this
dependency's defaults or a custom video relation.

The two existing implementations are not wire- or parameter-compatible as-is:
LNP22 `nizk.DefaultParams()` uses the Dilithium ring `N=256, q=8,380,417`,
while LaBRADOR's `Rq` is `Z_q[X]/(X^64+1)` for `q=2^32-99`. LNP22 BDLOP
defaults have `mu=3, lambda=3, ell=4`, hence ten randomness polynomials and
four message polynomials; the opening matrix contributes seven public rows.
Those cannot simply be copied into either backend's defaults. A new BDLOP key
could in principle be generated over the LaBRADOR ring and the seven equations
lowered into its sparse relation API, but that is only an implementation path
to investigate. The opening's Gaussian tail must be covered by the proof's
fixed witness norm; message bytes need an injective encoding and explicit
range/length constraints; parameters need independent Module-SIS/Module-LWE
analysis; and the commitment's hiding/binding modes must be selected and
proved for the exact key distribution. No interoperability with an actual
LNP22-generated key, secure parameter set, payload circuit, or video-capacity
measurement has been implemented or run. Therefore BDLOP is a
mathematically relevant construction candidate, not yet evidence of a secure
or usable system commitment.

A first Rust bridge probe was run in the same pinned Lazarus checkout. It uses
the BDLOP dimensions (`mu=3, lambda=3, ell=4`, ten randomness polynomials),
expands `B0`/`Bm` as separate deterministic uniform matrices directly over
LaBRADOR's ring, samples the opening with its discrete Gaussian sampler at
`sigma=1.55*2^5=49.6`, and encodes the seven opening equations as full-ring
linear constraints. The fixture was extended with four fixed-width byte slots:
each byte is reconstructed from eight boolean scalar witnesses, and message/
bit polynomials are constrained to be constant-term scalars. This adds 4
reconstruction rows, 32 boolean rows, and 2,268 coefficient-pinning rows (2,311
constraints total). The opening norm-squared was **1,601,036** under the fixed
**5,000,000** bound. `composite_prove` and `composite_verify` passed; changed
context and target mutations fail composite verification. Direct constraint/
principal checks reject `bit=2` and `byte=256`.

Executed in the pinned Docker image: `cargo test -p labrador --test
bdlop_opening_bridge_probe -- --nocapture` -> **1 passed, 0 failed** (179.12 s
test runtime; 21.71 s initial compile in the latest clean reproducibility
run). Rust review confirmed the constraint construction and negative checks.
The fixture is retained at
`benchmark/lazarus_bdlop_bridge_probe/bdlop_opening_bridge_probe.rs`; run
`benchmark/lazarus_bdlop_bridge_probe/run_probe.ps1` to clone the pinned source,
inject the test and reproduce it in Docker. The clean runner invocation also
passed with the same norm and result. This is one feasibility run, not a
distributional benchmark; it already shows that proving a tiny four-byte
opening with these constraints is far from a realtime path on this host.

This is stronger than the earlier tiny matrix plumbing probe, but remains a
bridge experiment, not an implementation interoperating with the Go BDLOP API:
the public key is deterministically expanded in Rust, and the Gaussian width
is 49.6 rather than the Go default 50. This does constrain exactly four
constant byte slots, but not arbitrary-length payload framing. The probe
establishes only proof of this fixed opening and four-byte encoding relation.
Its digest covers a key seed, targets, bound and context for this hard-coded
builder; it omits explicit matrices and constraint schema and is not a generic
canonical statement digest. No independent security estimate for these custom
ring/commitment parameters, zero-knowledge shim, complete proof codec, or
video-capacity result exists. The base LaBRADOR protocol deliberately omits
zero knowledge, so this probe must not be described as a ZKP. Keep the backend
disabled.

### SALSAA R1CS candidate review (2026-09-29)

Added `benchmark/results/salsaa_candidate_assessment_20260929.md` after a
primary-source review of SALSAA. It was a relevant general lattice/R1CS lead
at the time of that review, but is not adopted: the abstract's “argument of
knowledge” wording does not establish zero knowledge for the implementation
(full theorem review remains pending); the paper reports 979 KB for its
standalone argument while this project's Akiyo Q22/GOP1 operating carrier is
1,232 bits; and no app-specific H.264/payload relation or stable integration
API is documented. The paper separately reports 73 KB for folding, which is
not a substitute for the standalone application proof. These cross-source
sizes are a strong reason to require a measured relation-specific proof, not a
proof that all SALSAA configurations are impossible. No candidate code was
built or run. Overall acceptance remains unmet.

### Target relation and statement-contract audit (2026-09-29)

Added `docs/LATTICE_VIDEO_ZKP_RELATION_v0.1.md` as an explicit, non-acceptance
target relation and threat boundary. It defines verifier-pinned public inputs,
private payload/opening witness, a context-bound lattice vector commitment,
canonical carrier-normalized video commitment, fixed-size in-band envelope,
replay behavior, and precisely what the base relation does not prove. It also
records why a registered application predicate is required for provenance or
truth claims.

The current helper/API audit found that the existing SHA3 payload commitment
does not include video/session context; `embed()` passes `proof_bytes` (the
receipt commitment on the default lattice path) as `session_id`; the statement
includes an original-cover file hash that blind verification cannot recompute;
and video commitment verification requires externally supplied carrier
positions. These helpers are not a ZK proof and no current backend proves the
new relation. The draft is a design contract for selecting/implementing the
backend, not a claim that soundness, zero knowledge, blind extraction, or
camera provenance is already achieved.

### Newer RoKoko candidate (2026-09-29)

The newer RoKoko paper and official Rust implementation were reviewed after
the SALSAA survey; see
`benchmark/results/rokoko_candidate_assessment_20260929.md`. RoKoko now has a
documented experimental SNARK frontend with a claim language, so it is the
highest-priority candidate for the next full-theorem and proof-size review.
The implementation itself warns that SNARK mode is highly experimental. The
sources inspected here do not settle its concrete zero-knowledge guarantee,
do not implement this application's video/payload relation, and provide no
relation-specific proof-size result that fits the measured 1,232-bit Akiyo
operating carrier. A coauthor reports 106.70-115.58 KB for polynomial-opening
benchmarks at `2^22`-`2^30` dimensions, approximately 693-750 times the Akiyo
154-byte operating carrier; these are not measurements of this application's
relation and do not prove all configurations impossible. The standard-SIS
variant in that report is also not yet on the main branch. RoKoko was not
cloned, built or run. This advances candidate triage but does not pass any
ZK/video-embed acceptance gate.

For the same Akiyo scan, `raw_safe_bits=413415` (about 50.5 KiB of candidate
sign positions) is still smaller than the cited 106.70 KB proof alone by about
2.06x, before envelope framing or quality/reliability margin. This comparison
is limited to this measured clip and scan, but indicates the published smallest
proof point cannot fit the currently enumerated Akiyo candidate pool.

Source follow-up on the official frontend guide narrows the integration fit:
its claims are weighted sums of pointwise products over a committed
ring-element vector (degree at most three per variable), not arbitrary R1CS;
cross-index constraints require explicitly laid-out witnesses and copy claims.
The guide says the final folded witness is eventually read by the verifier,
which is a ZK review red flag but not alone proof of a violation. The paper's
formal theorem and its mapping to the implementation remain unverified because
the paper PDF could not be retrieved. The guide explicitly calls the SNARK
frontend experimental. Do not call it a ZKP backend until a theorem-level
review resolves whether and under what conditions witness hiding holds.

### Current public ZKP path revalidated (2026-09-29)

Re-read the current `embed()`, `verify()` and blind-verifier branches and
re-ran `test_lattice_zkp.py` (8/8) and `test_video_zkp_contract.py` (9/9).
The first suite confirms the experimental SIS prototype's prover-selected
statement flaw and that public APIs fail closed; the second validates only
statement/hash/registry helpers. Neither establishes a proof backend. The
default public path remains a signed ML-DSA receipt reference with sidecar,
not a lattice ZKP. Evidence and exact source locations are recorded in
`benchmark/results/current_zkp_path_revalidation_20260929.md`.

### LaZer Toolkit candidate follow-up (2026-09-29)

The official LaZer Toolkit source contains concrete ZK examples for
custom-hash Merkle membership and blind-signature commitment opening, making it
a stronger research candidate than the previous linear-only LNP22 probes. See
`benchmark/results/lazer_toolkit_candidate_assessment_20260929.md` for source
references and exact scope. It does **not** implement the required
verifier-pinned video/session/carrier relation. The paper's Fiat–Shamir and
composition knowledge-soundness reliance is characterized as heuristic in the
ROM; its custom hash has an explicit no-cryptanalysis caveat. The paper does
not give exact proof bytes, the Python API returns in-memory C structures, and
this host fails the upstream AVX-512F requirement. The candidate is therefore
marked “revisit,” not integrated; all application-level acceptance gates
remain open.

The pinned `blind_signatures.py` benchmark also seeds `compute_commitment()`
from the public constant byte `01`, so its commitment randomness is predictable
and repeated; it must not be reused as-is for a privacy claim. The same example
uses a fixed one-polynomial (512 binary-coefficient) message shape. A
production adaptation requires fresh CSPRNG entropy, canonical payload/context
encoding, and new relation/security review.

Full-paper follow-up refined, but did not clear, this decision. The official
PDF's Theorems 1 and 2 state knowledge-soundness error bounds under their
specified M-SIS conditions; the paper characterizes the Fiat–Shamir/composition
knowledge-soundness reliance as heuristic in the ROM. Its blind-signature
application has a commitment-opening relation relevant in shape to a hidden
payload, but uses an unreviewed custom hash and does not bind this system's
video/session/carrier statement. The paper estimates ZK proof size at around
110 KB but explicitly does not give exact serialized sizes; the Python API
passes C structures in-process, and the pinned native `pack_proof` / `pack_params`
APIs expose pointer-rich objects without a serializer in the reviewed `pack.c`.
This estimate
exceeds Akiyo's raw candidate ceiling (~50.5 KiB), while a prior Coastguard
patchability scan found a larger potential budget (~131.7 kB) but did not
validate quality or embed/extract any proof. See the candidate assessment for
qualifiers, source locations and fresh local preflight/test results.

The repository's `lazer/LAZER.lock.json` still pins commit
`10eafeca4cd53ff4fc54193dce904dbd0026fefd` and the earlier `A*s=t` demo; the
upstream README pins this Toolkit to
`59a52f74ca39584edf77b4b8b7437dbd48f9ad94`, whose `src/labrados` submodule is
pinned to `3f95485139ffaa65fe572da809b90772901372e5`. Both candidate revisions
are now recorded in `lazer/LAZER_TOOLKIT_CANDIDATE.lock.json`. This gives source
provenance but is not a reproducible build artifact: the host still lacks
AVX-512F and the proof has no reviewed wire codec. Keep the active backend lock
unchanged; a candidate pin and a runnable, reviewed serializer are separate
requirements.

### Ringo-SNARK / Buckler candidate recheck (2026-09-29)

A later candidate review found Ringo-SNARK, a Go implementation of the
Buckler zero-knowledge PIOP with Jindo polynomial commitments. The pinned
Go-proxy revision is `v0.0.0-20260924001507-306742714785` (VCS commit
`3067427147851b07024706780fa4cfe681c62c27`, checksum recorded in
`benchmark/results/lattice_zk_alternatives_assessment_20260929.md`). Unlike
LaZer Toolkit, it builds and runs on this Windows host without AVX-512.

Fresh evidence: `go test ./buckler/...` passes; the upstream rank-8192
`examples/mult` actually generated and verified its example proof (264.663 ms
prove, 37.376 ms verify). This is a real candidate proof, but its relation is
only example multiplication plus a norm bound. The printed 0.507719 MiB is an
estimated combined commitment+proof size (`Parameters.Size()`), not measured
serialized proof bytes; it is around 10.3x the Akiyo profile's 50.5 KiB raw
carrier ceiling before framing. Treat this only as a capacity warning, not a
universal impossibility result.

An additional local run of the pinned `examples/bfv` circuit verified a BFV
ciphertext well-formedness proof with a private message, secret key and bounded
error: prover 1.1405089 s, verifier 83.0357 ms, `Verification result: true`.
This is structurally closer to a commitment-opening relation but still does
not bind a payload to the verifier's canonical video/session/carrier context.
Its Jindo combined commitment+proof **estimate**, 1.103583532560498 MiB,
corresponds to approximately 1,157,191 bytes, about 107.4 times the 10,779
bytes used in the real 3,000-frame Coastguard blind transport probe. It is not
measured Buckler proof bytes and the relations differ; this is a concrete
capacity-risk signal for this carrier, not a universal infeasibility result.
Command, output and source-size semantics are recorded in
`benchmark/results/lattice_zk_alternatives_assessment_20260929.md`.

The latest pinned README marks its Strong Fiat-Shamir item complete (correcting
the earlier source-search note that treated it as TODO); its implementation
uses a named SHA-256 Fiat-Shamir transcript. However, source inspection found
that `buckler/prover.go:124` and `buckler/verifier.go:68` initialize the
transcript without public statement/context input. The initial `projConst`
challenge is preceded by binding prover witness commitments, while public
witnesses are encoded separately and used later in verifier checks; the
reviewed revision does not visibly bind a canonical statement digest before
challenges. Buckler's paper distinguishes static Fiat-Shamir (hash the first
prover message) from adaptive Fiat-Shamir (hash the public instance and first
message). This application's prover chooses its video/payload statement after
receiving the verifier's one-use challenge, so its intended security model is
adaptive. This is a concrete review gate, not a claim that an exploit has been
demonstrated or that the paper's HVZK theorem is false. Resolve it by a
theorem-backed equivalent using verifier-fixed relation/public input or a
reviewed transcript extension. The repository labels itself under
construction. Its
proof is an in-memory struct with no complete canonical wire serializer found,
and there is no application proof for a payload-commitment opening bound to
canonical video/session/carrier context. No video was embedded or
blind-extracted using this proof.

Disposition: Ringo/Buckler remains a runnable candidate, but is no longer the
top next step for the linear-commitment statement-v4 route. The newer pinned
Lazarus/LaBRADOR source exposes sparse linear/quadratic application constraints
and passes its crate tests in an isolated container; its four-byte BDLOP-shaped
relation probe is still not zero knowledge and not a video proof. Ringo's BFV
proof is likewise not the application proof, and its statement-transcript
binding remains unresolved. Keep both research paths under review; neither is
an accepted backend. Preserve all existing acceptance criteria; do not turn a
generic example, a BFV example or a passing crate suite into a video-ZKP
success claim.

### Transport versus application-proof gate (2026-09-29 recheck)

An isolated Go relation probe now exists at
`benchmark/lnp22_context_probe/payload_opening_probe.go`. Unlike the old fixed
random-witness proof, its public two-polynomial commitment is algebraically
derived from three short randomness polynomials, exactly 256 private payload
bits (32 bytes), and a domain-separated public context digest. A third linear
row imposes `bit + complement = 1` coefficient-wise. This encodes bits only
**if** the proof enforces the exact `Beta=1` witness bound; the pinned Go
verifier does not, as the counterexample below demonstrates. The verifier derives
the matrix from its pinned seed and reconstructs the public statement. The
targeted test generated an actual 8,203-byte LNPF-v2 proof and rejected
changed context, commitment, matrix seed, payload under the same opening,
tampered proof bytes, and malformed inputs. Code review then found that a
fixed matrix plus a public additive context term permits recentering the
commitment under a different context and **reusing the same proof**. A new
regression test reproduced that failure. The experimental matrix expansion
now also depends on the context digest, so this specific substitution test
rejects. This does not prove non-malleability or replace the target relation's
requirement that the complete public statement enter a reviewed transcript.
`go test -count=1 ./...` and `go vet ./...` in that Go module passed. A later
dependency assessment bypassed only `ProveLinear`'s prover-side norm preflight,
constructed the same Fiat-Shamir response, and produced a canonical proof
accepted by `VerifyLinear` for the false statement `s[0]=2` under `Beta=1`.
The payload probe's own matrix likewise accepted a serialized transcript
created from a bit coefficient 2 and complement -1 (without establishing
that no alternative short opening exists for that second commitment). These
tests prove that the 8,203-byte proof **does not establish exact byte/bit
boundedness**. The linear Go backend is rejected for this target relation
until a separate reviewed boundedness proof exists. This is relation-plumbing
evidence, **not** an accepted lattice ZKP: no concrete hiding/binding review
exists, video canonical context is not connected, and no 8,203-byte proof has
been put through the H.264 carrier.
See the probe README for reproducibility and threat limits.

The retained `benchmark/results/lnp22_video_e2e_compact_20260928T1109.json`
reports a completed real H.264 transport run: a 9,227-byte LNPF-v2 proof was
carried in a 10,779-byte blind envelope using 86,232 residual carrier bits.
The 3,000-frame Coastguard output passed strict H.264 decode; video-only
extraction recovered the proof and the Go verifier returned `valid: true` for
the pre-provisioned short linear relation. This is evidence that the transport
can carry a complete proof artifact on that particular long clip. It is not
evidence that the proof establishes the payload-commitment opening or any
application predicate. The corresponding probe test explicitly demonstrates
that the same fixed witness proves under distinct payload-commitment context
values.

That run took 16,931.57 seconds before artifact publication, including
3,229.54 seconds for cover analysis/carrier selection, 4,450.90 seconds for
embedding/strict decode, and 9,229.57 seconds for blind extraction plus
verification. Observed peak process-tree RSS was 3,664.95 MB. These are one
run's measurements, not a realtime or representative benchmark. The retained
video and JSON reports are present, but the original sync key is not available
in the current environment; no fresh re-verification of that particular video
is claimed here.
Fresh read-only checks of the retained output found the recorded SHA-256
`3537250821090b0b4fb08a51429f640ce736857ea6026a1c59086633f99b226b`,
`ffprobe -count_frames` reported 3,000 H.264 frames at 352x288, and
`ffmpeg -v error -xerror -err_detect explode ... -f null -` exited 0 with no
diagnostics. These checks confirm the retained artifact's identity and current
decode compatibility, not a fresh proof extraction or cryptographic verdict.

The target relation remains the critical missing gate. Reusing the LNP22
transport or adding another byte-envelope wrapper would not fix the fixed
linear relation's missing payload-opening proof or its pinned verifier issues.
The active `embed()` path also emits only an ML-DSA receipt reference; its
optional future statement uses ordinary carrier positions and lacks the
`carrier_profile_hash` required by the video-only context helper. The new
`zkp_session_id` argument corrects only the session-challenge field. Before
claiming a combined system, the selected reviewed lattice-ZK backend must
prove the exact registered payload-opening relation, expose complete canonical
proof bytes, and be tested through the existing in-band transport with
independent video-only verification and measured quality/capacity.

### Ringo/Buckler application-opening probe (2026-09-29)

The pinned Go Ringo candidate now has an executable, research-only 32-byte
opening-shaped circuit with Boolean payload slots, fixed zero tail, ternary
randomness and two full-ring commitment equations. The probe initially trusted
prover-side public matrix/mask vectors; review found that a zero mask removes
the tail restriction. Its `verifyOpening` wrapper now accepts only an
independently known context, public commitment and proof, and derives the
matrix/message/mask itself. Tests verify a valid proof, reject changed context
while holding the commitment fixed, reject changed commitment and malformed
witnesses, and show a weak-mask proof passes the raw API but fails the wrapper.
`go build`, `go vet`, `go mod verify`, and ordinary `go test` pass. See
[`benchmark/results/ringo_opening_probe_20260929.md`](benchmark/results/ringo_opening_probe_20260929.md)
for the exact scope and commands.

This does **not** close the backend gate. The context is not the canonical
video/session statement, the commitment construction/parameters and adaptive
Fiat–Shamir binding are not reviewed, and there is no complete proof wire
codec. Jindo's **550,249-byte estimated** commitment-plus-proof size is about
51.05 times the envelope carried in the earlier Coastguard experiment; it is
not measured serialized proof bytes or a universal capacity lower bound. Plain
race testing also hits an upstream CRT assembly `checkptr` failure. Keep this
module outside the production registry; no in-video lattice ZKP is claimed.

### Ringo/Buckler proof-wire measurement (2026-09-30)

Added bounded, canonical JSON and schema-pinned binary codecs for the complete
`buckler.Proof` object, including shape rejection before verification and
panic-to-rejection handling at the probe verifier boundary. A decoded binary
proof verified successfully. In the recorded run JSON measured 2,710,137 bytes,
the binary encoding 1,653,727 bytes, and `JindoParams.Size()/8` estimated
550,249 bytes. Gzip BestCompression produced 1,281,918 bytes. JSON, binary and
gzip therefore remain about 251x, 153x and 119x the measured 10,779-byte
Coastguard envelope. One run measured 26.46 ms compile, 300.89 ms proving,
126.79 ms verify, 65.21/145.78 ms JSON encode/decode and 46.21/100.02 ms binary
encode/decode; these are single local samples, not a benchmark distribution.
These formats do not fit that carrier; this says nothing universal about other
videos. They are research codecs, not production wire formats, and do not
address the unreviewed commitment/security parameters, CRS generation,
video/session canonicalization, or the separate plain-race upstream failure.
The retained 3,000-frame Coastguard raw-capacity scan found 4,332,560 raw-safe
bits (541,570 bytes) before patchability and quality losses. The proof-only
binary size plus 16-byte framing is 1,653,743 bytes (3.05x that raw upper
bound), but omitted the verifier's public commitment and statement. The
complete minimum envelope is 1,916,177 bytes, and the fixed carrier profile is
2,000,000 bytes (3.69x the raw bound); this exact cover cannot carry the full
verifier input. No in-video Ringo proof run was attempted. Full measurements
and commands are recorded in
[`benchmark/results/ringo_opening_proof_wire_recheck_20260930.md`](benchmark/results/ringo_opening_proof_wire_recheck_20260930.md).

The Ringo path still cannot be promoted: the probe is not integrated with
H.264 embedding/extraction or the public APIs, has no independent cryptographic
review, and has not demonstrated a compact proof that fits the measured
3,000-frame Coastguard carrier. The default shipped path remains the ML-DSA receipt
reference with a sidecar; it does not satisfy the active lattice-ZK goal.

Follow-up profiling logged the binary proof's 639,289-byte witness commitments
(13 items) and 1,014,194-byte evaluation proof; `EvalProof.Encode` alone is
557,295 bytes. BestCompression of that binary sample was 1,246,186 bytes, still
2.30x the 541,570-byte raw-capacity upper bound. The actual Jindo CRT moduli
were 42-bit (inner) and 38-bit (outer), but the experimental codec writes each
residue as a 64-bit word. Even the optimistic estimate that reduces the entire
proof by 42/64 remains about 1.09 MB before framing and carrier/quality losses.
This is diagnostic evidence against expecting basic coefficient bit-packing
or gzip alone to make the tested clip fit; no compressed-CRT codec or video
embedding was implemented. The sample details are appended to the wire-format
recheck report linked above.

A one-run rank sweep also proved, serialized, decoded and verified at ranks
256/512/1,024/2,048/4,096. Rank 256 exactly fits this 32-byte payload without
zero-tail padding, yet its proof was 998,087 bytes binary and 706,510 bytes
gzipped, still 1.84x/1.30x the raw-capacity bound; proving/verification took
36.11/13.63 ms locally. Lower rank is not endorsed as a secure parameter: no
independent analysis establishes its security, and reducing rank alone did not
fit this carrier. The full table and commands are in the linked report.

The probe now derives its public matrix from a canonical 282-byte `RGOS` v1
statement containing the session challenge, normalized-video commitment,
carrier-position hash, codec/carrier profile, relation/parameter/registry IDs,
epoch, payload length and carrier count. Reusing a proof while changing each
of those tested context fields is rejected with the public commitment fixed.
The test digests remain fixtures: video hashing, blind position derivation,
trusted registry resolution, spent-token tracking and challenge expiry are
not implemented in this probe. This is relation plumbing, not production ZK.

The probe's fixed-profile `RZV1` envelope now includes the complete 282-byte
statement, rank-8192 262,152-byte canonical public commitment, and binary
proof, with zero padding to the verifier-pinned carrier count. It round-trips a
2,000,000-byte envelope and verifies the decoded proof; malformed lengths,
truncation, bad magic and nonzero padding are rejected. This validates only a
transport codec: the Ringo proof is still not embedded/extracted from H.264,
and the measured 3,000-frame cover's raw-capacity upper bound is only 541,570
bytes.
