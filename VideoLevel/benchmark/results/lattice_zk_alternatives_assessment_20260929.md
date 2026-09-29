# Alternative lattice-ZK backends: source review (2026-09-29)

## Result

No reviewed, currently available implementation found in this search satisfies
all three gates at once: (1) verifier-pinned application computation including
video/payload binding, (2) zero knowledge in the actual selected backend, and
(3) an independently reviewed implementation suitable for integration. The
closest *future* architecture found is Jolt with the Akita lattice polynomial
commitment backend, but it currently fails the zero-knowledge gate. Do not
integrate it as a replacement for the required proof.

The initial Jolt/Akita and Lantern comparison below is a source and paper
review; no code for those two candidates was built or run here. Later sections
record separate local builds and executions for Lazarus/LaBRADOR and Ringo.
Upstream-reported benchmarks are not measurements from this host.

## Jolt + Akita

Akita is a lattice-based polynomial commitment backend, not a complete
application proof system by itself. Jolt can execute a guest program, so it
could eventually provide a route to pinning a verifier-side computation over
the canonical video and payload statement. However, the current
[Jolt Akita documentation](https://jolt.a16zcrypto.com/how/akita.html)
explicitly states that Akita supports clear proofs only; the `akita` and `zk`
features are mutually exclusive, and BlindFold's zero-knowledge path applies
to the Dory backend. A clear execution proof does not meet this goal.

LayerZero's [Akita announcement](https://www.layerzerolabs.org/blog/introducing-akita)
reports proof sizes around 65-80 KB for its applications. This is an
upstream-reported range, not a local reproduction or a size for this video's
application relation. Even its lower end is about 430 times Akiyo's 1,232-bit
operating capacity (or 260 times its 2,000-bit patchable capacity) in
[`sec2_capacity_data.json`](sec2_capacity_data.json). Other, longer videos may
have more capacity; no universal impossibility is inferred from Akiyo.

Akita's own [security policy](https://github.com/LayerZero-Labs/akita/blob/main/SECURITY.md)
says it has not received a formal production audit. Jolt's
[repository](https://github.com/a16z/jolt) describes the system as alpha and
not suitable for production. Those gaps are in addition to the missing ZK
backend and the unimplemented video/payload relation.

**Decision:** watch for a reviewed Akita-compatible zero-knowledge backend,
but do not use current Akita/Jolt to claim ZK. Reconsider only after zero
knowledge is enabled on the lattice PCS path, the exact application relation
is implemented and tested, a security review covers the resulting system,
and the serialized proof fits a quality-validated carrier.

## Lazarus

The current [Lazarus repository](https://github.com/lattice-complete/Lazarus)
is an actively changing Rust framework and warns against production use. Its
README roadmap lists proof serialization/entropy coding and a binary-R1CS
front end as pending. The `main` branch was rechecked at commit
[`4363e5151a25dac2e96885cd08c1bdfb7ac3c1af`](https://github.com/lattice-complete/Lazarus/tree/4363e5151a25dac2e96885cd08c1bdfb7ac3c1af)
on 2026-09-29; this is materially newer than the earlier Lazarus assessment.

### Pinned LaBRADOR port recheck

- The pinned Rust workspace contains a LaBRADOR `labrador` crate. Its
  `PrincipalStatement` API expresses sparse linear/quadratic ring constraints
  and a witness norm bound; `composite_prove`/`composite_verify` implement a
  recursive proof path. This makes it a plausible *research backend* for the
  separately proposed linear-commitment v4, but not for the current SHA3
  payload-opening v3 contract: the binary-R1CS/Dachshund front end and
  `quadratic==2` mode remain listed as unimplemented in the pinned
  [migration map](https://github.com/lattice-complete/Lazarus/blob/4363e5151a25dac2e96885cd08c1bdfb7ac3c1af/docs/MIGRATION.md).
- Source at that commit defines `CompositeProof` only as in-memory
  `rounds` plus `final_witness`; the composite verifier consumes that object.
  The migration map explicitly puts compact proof encoding/entropy coding in
  the next steps, and the crate has no `serde` dependency or complete proof
  codec. A field-vector `to_bytes()` method is not a canonical full-proof wire
  format. The source's “final witness in the clear” needs an explicit
  theorem-to-implementation privacy review before using this proof path for a
  private application witness; this observation alone does not establish a
  leak or refute the paper's theorem.
- The code seeds its first reduction transcript from `PrincipalStatement.h`
  (`Input::hash()`), so a future wrapper could derive that value from the
  verifier's canonical public statement. This is only a binding hook: no
  wrapper currently constructs a verifier-pinned video relation, no test
  validates statement-replay resistance, and field values/lengths/constraint
  layout must be canonically encoded before hashing.
 - The migration notes say the Rust protocol formulas are ported but are not
   byte-compatible with the C reference; they record sampling/backend
   differences, a coarse root-Hermite-factor MSIS estimator requiring
   recalibration, and missing proof serialization. The project itself warns
   against production use. **Correction:** the underlying LaBRADOR paper
   explicitly disregards zero knowledge for its base proof system and only
   suggests adding a linear-sized witness-masking shim to obtain it
   ([paper](https://eprint.iacr.org/2022/1341.pdf)). That shim is absent from
   this pinned Rust proof path and has not been implemented or reviewed here.
   Thus the candidate does not currently meet the ZK gate; the visible
   `final_witness` is in the clear. The paper's knowledge-soundness result does
   not imply witness privacy.
- The source was shallow-cloned outside the worktree at the pinned commit and
  inspected. Since the host has no `rustc` or `cargo` executable available, it
  was built/tested in Docker image
  `rustlang/rust:nightly-slim-2026-09-15` (digest
  `sha256:66726eb549e867024ed4b890cb133e7304b52cc2f380d425b7ce210849970894`):
  `cargo test -p labrador` completed with **35 passed, 0 failed** (24.22 s
  compile; 2.02 s tests). Tests include toy sparse-relation proof rounds,
  composite verification and tamper rejection. They do not test the proposed
  payload commitment, video context, blind extraction, full-proof
  serialization, or zero-knowledge leakage of the final reduced witness.
  Upstream README benchmark numbers are not application measurements and are
  not used as proof-size evidence.
- A fixed-statement plumbing probe was then extended to a two-row q-ary linear
  form `C=A*r+G*u` plus one-hot constraints. The valid `C=(-12,-12)` opening
  proves/verifies; changed context and a changed public row reject the proof.
  A non-bit witness under the same C/bound satisfies the linear rows and
  `u+v=1` but fails `u^2+v^2=1`. More importantly, the deliberately tiny matrix
  explicitly fails binding: a second *valid* bit-0 opening to the same C also
  passes principal verification. `cargo test -p labrador --test
  linear_commitment_probe` reported **1 passed, 0 failed** (4.22 s test
  runtime). This is relation-plumbing evidence and a negative security result
  for these toy parameters, not a secure commitment. The harness remains in
  the external temporary clone, and the probe's `h` hashes only its fixed
  schema inputs, not arbitrary statement constraints. It does not establish
  application ZK, secure parameters, proof serialization, H.264 embedding, or
  video capacity.
- A separate BDLOP-shaped opening bridge uses `mu=3, lambda=3, ell=4`,
  deterministic uniform `B0`/`Bm` matrices over LaBRADOR's `R_q`, a discrete
  Gaussian opening at sigma 49.6, and all seven full-ring equations. It adds a
  fixed four-byte encoding relation: eight boolean witnesses per byte,
  reconstruction rows, and constant-coefficient pinning (2,311 constraints
  total). The opening norm² is **1,601,036** under `betasq=5,000,000`; positive
  composite prove/verify passed, changed context/target composite verification
  rejected, and direct relation checks rejected bit=2/byte=256. Clean
  reproducibility command:
  `benchmark/lazarus_bdlop_bridge_probe/run_probe.ps1` -> **1 passed, 0 failed**
  (179.12 s test runtime; 21.71 s clean initial compile). A Rust reviewer
  confirmed the equations and encoding constraints. This is not interoperability
  with the Go BDLOP code: it uses a Rust-deterministically-expanded key, and
  sigma 49.6 differs from the Go default 50. One run on four bytes is not a
  benchmark distribution, but shows this path is nowhere near realtime on this
  host. The context digest omits explicit matrix and constraint encoding; no
  security parameter analysis, hiding/binding proof, application ZK review,
  proof codec, or video-capacity test was done. The fixture and runner are
  checked in under `benchmark/lazarus_bdlop_bridge_probe/`; the earlier tiny
  matrix probe remains external to the project tree.

**Disposition:** promote Lazarus/LaBRADOR from “not implemented” to a
*focused v4 linear-relation research candidate*, not an accepted backend. Its
current source is still unusable for the target system until the application
relation and ZK boundary are reviewed, the complete proof has a canonical
serializer, concrete security parameters are independently checked, the
candidate is built/tested, and actual proof bytes fit a quality-validated
blind-extractable H.264 carrier. Do not confuse the paper's generic R1CS
result or the Rust port's sparse-relation API with a completed video proof.

## Lantern / LNP22 implementation

The [Lantern tutorial and implementation](https://lattice-zk.isec.tugraz.at/)
is a readable research implementation in SageMath, not a hardened production
backend. Its authors report 21.5-24 KB for simple commitment-opening plus
linear/quadratic-relation proofs at the stated 128-bit parameterization, and
29 KB / 35 seconds for the Module-LWE-secret example. They explicitly state
that its built-in random sampling is not cryptographically secure, it is not
side-channel hardened, and Lantern is not suited for large circuit
satisfiability statements. These source limitations are consistent with the
current repo's LNP22 experiments: a context-bound fixed linear relation still
does not prove payload-commitment opening, and the pinned alternative
two-ring verifier has a demonstrated soundness forgery (see the LNP22 sections
of `PQ_VIDEO_ZKP_PLAN.md`).

The pinned Go module `github.com/KarpelesLab/lnp22@v0.1.1` used by this
project is distinct from Lantern's Sage implementation; Lantern's sampler
warning is not evidence about the Go sampler. A later isolated Go probe in
`benchmark/lnp22_context_probe/payload_opening_probe.go` expresses a
32-byte payload-opening-*shaped* linear relation with a verifier-derived
matrix/context and an actual 8,203-byte serialized proof. Its negative tests
pass after a review-driven fix to a public context-offset substitution that
had reused the same proof under a changed `(context, commitment)` pair. The
experimental matrix now varies with the context digest; this is not a formal
non-malleability argument. A subsequent, more decisive assessment generated
a canonical proof accepted by the pinned `VerifyLinear` for a statement whose
first equation is `s[0]=2`, despite `Beta=1` and no in-bound solution. The
same verifier also accepted a transcript generated from a non-bit witness
under the payload-probe matrix. The ordinary `ProveLinear` call rejects those
witnesses, but a prover-side preflight is not a verifier-enforced relation.
Thus the 8,203-byte artifact is **not proof of exact payload-byte range**.
The selected commitment also has no reviewed hiding/binding or concrete
security estimate. No video proof was created with this relation. The Go
linear backend remains rejected for the target relation; the original LNP22
paper must not be treated as validation of this pinned implementation.

## Candidate disposition

| Candidate | Application relation | Actual zero knowledge | Current evidence | Decision |
|---|---|---|---|---|
| Jolt + Akita | General guest execution is plausible; video/payload guest absent | No on Akita backend | Official docs say clear-only; security audit absent; reported size 65-80 KB | Future watch; reject now |
| Lazarus / LaBRADOR | Sparse linear/quadratic relation available; binary-R1CS SHA3 v3 frontend absent; fixed four-byte v4-shaped bridge tested | **Base paper protocol is explicitly non-ZK; its proposed masking shim is absent. Current path fails ZK gate.** | Pinned source has no complete proof codec; crate and bridge tests ran in Docker because the host has no Rust toolchain; parameter estimator requires recalibration | Focused v4 relation-plumbing research only; not a ZKP backend |
| Lantern / Go LNP22 | Go probe now has a 32-byte payload-opening-shaped linear relation, not a full video application relation | Protocol has ZK claims; Lantern Sage sampler warning does not transfer to the separate Go module, whose verifier/extractor still need review | Lantern research measurements 21.5-24 KB; local Go probe proof 8,203 bytes, with known Go dependency gaps | Do not integrate now |

The strongest future path from this search is a Jolt-style verifier-pinned
program relation over video/payload plus a lattice PCS that actually supports
zero knowledge. That is a research direction, not a currently working system
or a relaxation of this goal.

## Candidate recheck: Ringo-SNARK / Buckler (2026-09-29)

This section is a later recheck and supersedes the previous statement that
Jolt/Akita was the closest future lead. Ringo-SNARK's Buckler PIOP with Jindo
PCS is a runnable software candidate: it has an API for secret/public
witnesses, arithmetic/linear/norm constraints, and a Rust-independent Go
implementation that ran on this Windows host. The later BFV capacity recheck
below makes it a lower-priority transport candidate for the measured clips.
It remains research-only, not an accepted application backend.

### Pinned source and local execution

- Retrieved from the Go module proxy as
  `github.com/sp301415/ringo-snark@v0.0.0-20260924001507-306742714785`, VCS
  commit `3067427147851b07024706780fa4cfe681c62c27`, module sum
  `h1:h0/R9a7T+wQn/6ZdX/nMcylDbh8a091BNIkoWIYq/yE=`. This download was placed
  in the Go module cache; it did not modify this project or add Ringo as a
  dependency.
- `go test ./buckler/...` passed on Windows/amd64 with Go 1.26.2:
  `buckler` 1.499s, `zp110` 2.326s, `zp220` 3.316s, `zp440` 3.772s; two
  architecture-specific assembly directories had no tests.
- `go run ./examples/mult` completed a real, upstream example proof/verify at
  rank 8192: prover 264.663 ms, verifier 37.376 ms, `Verification result:
  true`. The relation is an example multiplication/norm claim, not a video
  payload commitment or the target application statement.
- The example prints `prover.JindoParams.Size()/2^23` as "Estimated Proof Size".
  The source defines `Size()` as estimated commitment size plus proof size, so
  this run's `0.5077193017150599` is an estimated combined commitment+proof
  size of about 0.508 MiB, **not** measured serialized proof bytes. On the
  local Akiyo scan this estimate is about 10.3x the 50.5 KiB raw-safe carrier
  pool, before framing; that cross-example comparison is only a capacity-risk
  signal and proves no universal impossibility.
- `buckler.Proof` is an in-memory Go struct. Inspection found no
  `MarshalBinary`/`UnmarshalBinary` implementation for the Buckler proof or
  Jindo proof object in this revision. Existing binary serialization methods
  are for internal field vectors and do not define a canonical full proof
  format.

### Security and application-fit limits

- The pinned README labels the library "under construction." It marks the
  "Strong Fiat-Shamir Transform" and automatic parameter selection as done in
  the latest source, correcting the earlier assessment that strong FS was
  still TODO. The source uses a SHA-256 named-challenge transcript, but source
  inspection found that this integration has not established the required
  adaptive statement binding:
  `buckler/prover.go:124` and `buckler/verifier.go:68` initialize that
  transcript without a public-statement/context input. Before the first
  `projConst` challenge, the prover/verifier bind witness commitments
  (`prover.go:192`, `verifier.go:90`); the public witness vectors are encoded
  separately (`prover.go:166`, `verifier.go:73`) and used later by verifier
  checks (`verifier.go:183+`), but this revision has no transcript bind of a
  canonical statement digest. The [Buckler paper](https://eprint.iacr.org/2024/1879.pdf)
  defines the PIOP over a public instance `x`. A separate [Fiat-Shamir
  security analysis](https://eprint.iacr.org/2023/1945.pdf) distinguishes
  hashing only the first prover message for *static* security from hashing
  `(x, a)` for its *adaptive* security variant. In this system, the prover
  chooses the payload/video statement after receiving the
  verifier's one-use challenge, so the intended model is adaptive. This source
  review therefore cannot show the required context binding. It does **not**
  by itself establish an exploit or disprove the paper's HVZK theorem. Before
  integration, either establish a theorem-backed equivalent using a
  verifier-fixed relation/public input, or extend and review the transcript to
  bind the canonical statement. A checked README box is not an audit.
- Buckler's API can express arithmetic relations over its ring elements; this
  alone does not provide a reviewed bit-constrained SHA3/hash gadget or the
  exact relation `C = Commit(payload, opening)` bound to the verifier's
  canonical session/video/carrier policy. That relation has not been written
  or tested here.
- No negative proof-tampering suite, independent verifier artifact, proof
  serialization, H.264 embedding/extraction, decoder validation, or
  application-specific proof-size measurement was performed.

### BFV well-formedness example recheck (local execution, 2026-09-29)

The same pinned Ringo revision includes `examples/bfv/main.go`. Unlike its
generic multiplication example, this circuit checks a public BFV ciphertext
against a private message, secret key, and bounded error. Its `Define` method
uses NTT linear checks, the ciphertext arithmetic identity, and infinity-norm
constraints on the private witnesses. This is useful evidence that Buckler's
constraint API can express an *encryption-opening-shaped* relation. It is not
the registered payload-commitment opening and does not include this project's
session challenge, normalized-video commitment, carrier positions, or a
verifier-pinned application predicate.

Ran from the pinned module directory on this Windows host:

```text
go run ./examples/bfv
Prover time: 1.1405089s
Verifier time: 83.0357ms
Verification result: true
Estimated Size: 1.103583532560498 MB
```

The printed `MB` value divides `JindoParams.Size()` by `2^23`.
`jindo/params.go` documents `Size()` as an **estimate** for its combined
commitments and proof; it is approximately 1.104 MiB or 1,157,191 bytes if
interpreted as bits divided by eight. It is **not a measured serialized
Buckler proof**, and Buckler's other fields/framing are not included in a
verified wire-size measurement. The 3,000-frame Coastguard experimental
transport in `lnp22_video_e2e_compact_20260928T1109.json` actually used
10,779 bytes / 86,232 bits of blind-extractable carrier. The BFV example's
Jindo size estimate is about **107.4 times** that *one video run's* used
capacity. These are different relations and this is only a feasibility
warning, not a universal lower bound on Buckler proof size or H.264 capacity.

Source recheck also confirms the public BFV ciphertext is assigned as
`PublicWitness`, while the first Fiat-Shamir challenge still binds only
witness commitments in `buckler/prover.go` and `buckler/verifier.go`; the
canonical public video/session statement is not absorbed before that
challenge. The BFV example's successful verification does not resolve the
adaptive-statement security question. No exact application proof, canonical
proof serializer, negative test suite, or video embedding was produced.

### Disposition

Ringo/Buckler remains a runnable candidate for focused relation-design and
security review because both a generic proof and an encryption-shaped BFV
proof run without AVX-512 on this host. The BFV example moves relation-API
confidence forward but raises a major video-capacity risk. It is not the
closest next step for the linear-commitment v4 route: the newer pinned
Lazarus/LaBRADOR source exposes a sparse linear/quadratic relation surface and
passes its crate tests in an isolated container, though its current base
proof path is not zero knowledge. Do not integrate Ringo:
in addition to the missing application relation, reviewed concrete security
parameters, canonical proof wire format and measured fit in quality-validated
H.264 capacity, the visible Fiat-Shamir transcript does not absorb the public
statement/context before challenges, and the intended application uses an
adaptively selected statement. This changes candidate priority only, not the
system's acceptance criteria.

### Later application-opening-shaped probe

The separate [`ringo_application_probe`](../ringo_application_probe/README.md)
now executes a rank-8192, 32-byte Boolean payload-opening-shaped relation
with ternary randomness and two full-ring equations. An application-level
verifier independently derives the matrix and exact tail mask from its own
context; tests reject changed context with the *same* commitment, changed
commitment, invalid bit/tail/randomness witnesses, and a proof created under
an intentionally weak prover-selected mask. The initial verifier trust-boundary
defect was found in Go review and corrected. The detailed, dated execution
record is [`ringo_opening_probe_20260929.md`](ringo_opening_probe_20260929.md).

This supersedes only the statement above that *no opening-shaped relation had
been written/tested*. It does not satisfy the real application relation:
context is not the canonical video/session statement, the custom commitment
is not reviewed, and the proof is not serialized. Jindo reports **550,249
bytes estimated** for commitment plus proof, not actual wire bytes. That is
about 51.05 times the prior 10,779-byte Coastguard transported envelope and
is a serious fit warning, not a proven lower bound. Keep Ringo research-only.
