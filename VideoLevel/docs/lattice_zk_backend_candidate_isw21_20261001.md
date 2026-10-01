# ISW21 lattice zkSNARK candidate check (2026-10-01)

## Decision

ISW21 is the first candidate in this repository that passed a real upstream
Linux build and a prover/verifier smoke test for an application-shaped toy
R1CS on the current computer. Keep it as a **research candidate**, not an
accepted application backend. The smoke constrains payload and context bits
against a toy linear commitment, but does not encode the target relation's
full session policy, registry binding, normalized H.264 statement, or secure
commitment parameters.

The upstream project explicitly describes itself as a proof-of-concept and
not production-ready. The construction is a *designated-verifier* lattice
zkSNARK: setup creates a verifier secret key. Any future integration must
therefore provision the verification key only to the designated verifier and
must not describe its proofs as publicly verifiable.

This is no longer the strongest paper-level candidate found for the required
knowledge-soundness property. The 2025/2099 preprint, revised July 2026,
claims adaptive knowledge soundness from MSIS in the random-oracle model and
combines an inner-product argument with an LPCP compiler. It is now the
highest-priority candidate for source/artifact review. Its abstract and
security claim are not independent validation, and no implementation of that
construction has yet been built or reproduced in this repository.

## Independent assumption review

A primary-source check of the ISW21 paper and the later LUNA analysis changes
how this candidate can be described for this project's knowledge relation:

- The upstream README states computational security parameter 128 and
  statistical zero-knowledge parameter 40 for its prototype. The latter is
  the stated distinguishing bound `2^-40 + negl(lambda)`, not a 128-bit
  zero-knowledge claim. The exact target policy must decide whether that
  statistical privacy level is acceptable and re-derive parameters for any
  change.
- ISW21 is designated-verifier preprocessing: the verifier has a secret key.
  The paper also states that the construction lacks reusable soundness against
  a malicious prover making an arbitrary polynomial number of verification
  oracle queries. It says attacks require a super-constant number of bad
  proofs, making attempts detectable under the paper's model; this repository
  has not implemented or analyzed the corresponding oracle/rate-limit policy.
- More critically for the requested *proof of knowledge*, the later LUNA
  paper says the knowledge-based linear-only LWE assumption used to obtain
  knowledge soundness for ISW21 and related schemes is invalid against
  quantum attacks. It distinguishes this from ordinary argument soundness:
  a weaker statistically-simulatable strict LTM assumption may still support
  ZK-SNARG soundness, while the knowledge-sound ZK-SNARK claim needs a stronger
  computationally-simulatable LTM assumption plus knowledge soundness of the
  underlying LPCP. That stronger assumption and the exact ISW21-to-application
  composition have not been established here. This invalidates that stated
  knowledge-assumption route; it is not, by itself, a demonstrated forgery or
  a proof that ISW21 is unsound under every alternative assumption.

Therefore, the observed honest verification and altered-public-input
rejections in the smoke test do not establish post-quantum knowledge
soundness for the payload-opening relation. Until an independent cryptographic
review selects and justifies a viable assumption path (or a different backend
with an acceptable knowledge theorem), ISW21 remains a proof-of-concept
integration candidate only; it is not evidence that this project's required
knowledge relation is securely proved.

## Newer standard-assumption candidate: ePrint 2025/2099

The latest ePrint abstract (revision dated 2026-07-13) describes *A
Lattice-based Designated Verifier zkSNARK from Standard Assumptions* by
Ahmadi, Eghlidos, Abdolmaleki, and Nguyen. The authors claim an inner-product
argument based on Module-SIS (MSIS) with adaptive knowledge soundness in the
random-oracle model, then combine it with an LPCP compiler for a designated-
verifier zkSNARK. This directly addresses two limitations relevant to the
ISW21/LUNA line: reliance on a lattice linear-only/targeted-malleability
knowledge assumption and knowledge soundness restricted to non-adaptive
attacks. These are the authors' claims for their construction, not a security
result independently checked for this project.

The current decision is therefore:

- **Prioritize 2025/2099 for artifact and theorem review**, not immediate
  integration. The full revised paper reports comparable prover/verifier
  times, 10x smaller public parameters, and 2.5x larger proofs than its stated
  baseline. The performance comparison excludes the shared LPCP work and uses
  simulated LUNA expansion/limited challenge counts, so it is not an
  end-to-end comparison. No benchmark from this repository reproduces it.
- **Keep ISW21 as the locally reproducible baseline only.** Its generic R1CS
  smoke test is useful for toolchain and proof-codec experiments, but the
  known quantum attack invalidates its stated knowledge-based LO assumption
  route, and the application relation remains absent.
- **Keep LUNA as a secondary comparison, not a drop-in replacement.** Its
  paper gives a ZK-SNARG route under a weaker statistically simulatable strict
  LTM assumption; its ZK-SNARK route needs computationally simulatable strict
  LTM and a knowledge-sound LPCP, and the proved soundness is non-adaptive.
  The public LUNA repository implements the HGSW encryption component
  (Setup/Encrypt/Add/Decrypt), not the full LUNA prover/verifier pipeline.

### Full-paper review and code artifact audit

The revised 31-page PDF was fetched directly from ePrint (SHA-256
`bb295e81b4e865e9a28cf9235fae0980d4da9d45412e71366c1650a9678f5faa`) and its
security, protocol, parameter, and evaluation sections were read. The web
reader returned 403, but a direct HTTP fetch succeeded; that was a reader
access issue, not a paper availability blocker.

The paper's security claim is more specific than its abstract: the DV-LatticeIPA
uses coordinate-wise special soundness and a rewinding extractor that needs
the setup trapdoors and a programmable random oracle. The paper claims
adaptive knowledge soundness in that random-oracle model, then composes the
argument with an LPCP compiler for R1CS. This is a useful candidate theorem
path, but it is not a standard-model knowledge-soundness result, and this
review has not re-proved the reduction or independently validated the
concrete MSIS estimate.

The paper reports, for its 128-bit parameter setting, 20.75 KB proof size and
1.3 GB full CRS; the proof size includes the commitment and response vectors.
The benchmark machine was Ubuntu 22.04.5, 4-core Intel i7-12700H, 8 GB RAM.
The plotted execution comparison excludes LPCP prover/verifier costs; its
LUNA setup/CRS-expansion comparison is partly simulated, and it extrapolates
from fewer challenges. Treat those figures as paper-reported component
measurements, not complete application timings. The proof is about 16.3x the
10,420-bit (1,302.5-byte) committed capacity measured on this project's
separate 300-frame Akiyo CIF native run, before adding the video envelope.
That specific clip is not a universal capacity bound, but it makes the
current 300-frame operating point plainly insufficient for this proof.

The paper links a public C implementation at
`crypolover1998/LatticeBased-Dv-zkSNARK`. It is now pinned for review at
`9bc41a62cd901c360d87f49a708b93c12238b5b8`; however, that repository's latest
commit is 2025-04-14, before the ePrint submission (2025-11-14) and revised
paper (2026-07-13). The repository exposes only the `main` branch at that
commit. Its sole open pull request, #1, is an update to `README.md` only
(one-line change); it contains no protocol implementation updates. At this
pinned source:

- `common.h` sets `PARAM_Lambda` to 1 and `PARAM_NumTrapdoors` to 4096;
- `mainprotocol.c` explicitly says it simulates the commitment phase and the
  PoK protocol for only lambda=1;
- after its single inner-product calculation, the program prints a value but
  does not make an accept/reject decision;
- the exposed prover interface computes commitments and two challenge
  responses, but the repo does not serialize a proof, implement the complete
  LPCP composition, or test malformed/tampered proofs.

Consequently, a public implementation artifact exists, but this checked
revision is a partial PoC and does not reproduce the complete revised,
128-bit, non-interactive DV-zkSNARK claimed by the paper. It cannot be used as
the project's proof backend as-is. Before reconsidering it, obtain a source
revision that matches the revised paper, pin and build it, verify its complete
setup/prove/verify and serialization behavior, test invalid proofs, and
independently review the adaptive extractor, programmable-random-oracle
argument, designated-verifier key lifecycle, and concrete MSIS estimates.
Then map the supported statement to this project's bounded payload-opening
relation and measure exact proof bytes against the selected carrier profile.
Until those gates pass, it remains a promising paper-level research lead and
**not** a usable project backend.

## Reproduced upstream test

- Source: `lattice-based-zkSNARKs/lattice-zksnark`, detached at
  `48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e`.
- Build/runtime: temporary Ubuntu 24.04 x86-64 Docker container on the
  project's Intel Core i7-12700H host, GCC 13.3, CMake 3.28; recursive
  submodules were checked out by the pinned upstream commit. Docker was
  configured with `WITH_PROCPS=OFF` because Ubuntu 24.04 does not provide the
  old package name used in the repository's setup notes.
- Command: `r1cs_lattice_snark_prime19_test 10000 100`.
- Outcome: C++ target built and the upstream verifier returned `PASS` for its
  generated 10,000-constraint R1CS instance (QAP degree 10,240, 100 public
  inputs).
- Observed timings from the one run: LWE secret-key generation 4.871 s; CRS
  and verification-key generation 9.291 s; prover 0.637 s; verifier 0.0006 s;
  total test 15.010 s. These are single-run smoke-test observations, not a
  benchmark distribution and not measurements of our application relation.
- Memory was not reported: this build used `WITH_PROCPS=OFF` and upstream
  printed `Memory profiling not supported in NO_PROCPS mode`.
- Upstream printed `Linear comb size 20146`. This is an internal number of
  linear-combination elements, **not** a serialized proof byte count.

## Corrected response-size feasibility bound

For upstream parameter class `B19C20`, the source fixes `n=2045`,
`query_num=8`, `query_size=4`, `pt_dim=32`, `tau=4`, and the message modulus
`p=2^19-1`. The ring modulus is instead `q=2^108`. The proof object contains
an `a_vec` of 2,045 quadratic-extension ring values and a `c_vec` of 36 such
values; each extension has two ring coefficients. `ciphertext::rescale()`
rescales these coefficients into a bounded interval; they are not 19-bit
message-field elements. The previous 19-bit estimate of 9,885 bytes was
incorrect and is withdrawn.

At the pinned upstream revision, `Ring::rescale()` first rounds a value below
`q` by `floor(q/rescale_q)`, then chooses a nearby representative congruent
modulo `p`. From that source operation, a conservative exclusive coefficient
bound is `rescale_q + p + 1 = 1,684,330,715,837`, which is below `2^41`.
Therefore a simple fixed-width packing needs 41 bits per coefficient. There
are `(2045 + 36) * 2 = 4,162` coefficients, giving:

```text
(2045 + 36) * 2 * 41 = 170,642 bits = 21,331 bytes after byte rounding
```

The smoke-test binary measured 4,162 response coefficients and a maximum
observed width of 41 bits in one real proof run, consistent with this source-
derived bound. The smoke test now implements a parameter-specific canonical
fixed-width response codec and successfully verifies a proof after
serialization and deserialization. Its exact output is 21,331 bytes. This is
an actual response encoding, **not a complete proof or application envelope**:
the format has no version/parameter ID, public statement, session metadata,
framing, or video integration. It is about 1.98x the
10,779-byte payload transported in one 3,000-frame Coastguard experiment and
2.23x the 9,568-byte raw-safe blind-stable capacity measured on a separate
300-frame Coastguard QP22/GOP1 input. The clips and capacity definitions differ;
neither comparison proves universal infeasibility, but both show a substantial
measured-video capacity risk that must be resolved with an application
envelope and quality-validated embed/extract test.

The closest native-path capacity evidence is a separate 300-frame Akiyo CIF
run with the project's patched x264 direct-CAVLC encoder: it committed 10,420
bits (1,302.5-byte equivalent) and failed closed on a 33,803-byte payload.
The response encoding here is 170,648 physical bits after byte rounding, about
16.4x that observed committed capacity before adding the native 14-byte
framing header. This is not an ISW-proof embedding trial and cannot establish a
universal limit, but it shows the current 300-frame IDR-only native operating
point is far too small for this response encoding. A simple linear projection
would require roughly 164 seconds of similar video; that is only a planning
estimate, since carrier availability and quality are content-dependent. See
the [ISW21 response capacity probe](../benchmark/results/isw21_response_native_capacity_probe_20261001.md)
for the exact run; the earlier [native payload capacity probe](../benchmark/results/native_payload_capacity_probe_20260930.md)
is the separate 33,803-byte comparison.

## Relation mapping required before integration

The target circuit should have verifier-pinned public inputs for the session
challenge, normalized-video digest, ordered carrier digest, codec/profile IDs,
registered parameter/relation IDs, and a lattice commitment. Private inputs
should be the payload bits and a bounded lattice opening. The circuit must:

1. constrain every payload byte to its canonical 8-bit encoding;
2. enforce the exact registered vector-commitment equation over the selected
   field, including the canonical context vector;
3. constrain every opening coefficient to the registered range; and
4. bind all public inputs to the exact statement reconstructed independently
   by the video-only verifier.

The production commitment dimensions/distributions and their SIS hiding and
binding estimates are not selected. Only the insecure toy relation below has
been implemented; the production relation, context encoding, transcript
composition, and parameters have not been implemented or reviewed. A passing
smoke circuit proves none of those properties for the target system.

### 32-byte application-shaped relation smoke (toy parameters)

The isolated ISW21 smoke circuit now constrains a full 32-byte private
payload, a 2,816-bit private opening, a 32-byte public context, and a
128-coordinate commitment. Its relation has the KTX shape
`C = A * (payload_bits || context_bits) + B * opening_bits (mod q)` and
constrains all commitment coordinates in the R1CS. It separately rejects an
altered payload witness and opening, and the proof checks reject changed
context/commitment and altered serialized response. This exercises the
intended witness shape and statement binding in the R1CS, but q is only 19
bits and no concrete SIS security estimate has been made. The generated
matrices are not a production key setup. This is not a secure commitment, a
production proof, or an H.264 integration.

Built against the pinned upstream revision
`48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e` in the Ubuntu 24.04 research
container, one observed run had 3,520 constraints, QAP degree 4,096, 160
public inputs, a 21,331-byte serialized response, 5.1720 s LWE secret-key
setup, 3.8536 s CRS/VK setup, 0.3281 s proving, 0.0006 s honest
verification, 9.82 s whole-process wall time, and 481,052 KiB peak RSS. This
was a single smoke measurement, not a benchmark distribution. Source review
found the pinned upstream revision closes a function-static `/dev/urandom`
stream after its first seed read and reuses it in later calls; subsequent seed
bytes may be uninitialized. This run was repeated after applying the tracked
[`upstream_rng_fix.patch`](../research/isw21_r1cs_opening_smoke/upstream_rng_fix.patch)
to the temporary upstream checkout. The patch opens a fresh stream for every
seed and rejects failed/short reads; it does not change the upstream source
repository. The result is now usable as limited smoke evidence, but is not an
independent cryptographic audit or secure-parameter validation. The response
length is fixed by the selected ISW21 proof parameters and remains 21,331
bytes; its exact in-band capacity gap is severe for the measured 300-frame CIF
profiles. A second fresh process after the same patch exited 0 with the same
honest-proof and negative-case markers (9.12 s wall time, 481,076 KiB peak
RSS). These are two smoke runs, not a benchmark distribution. The detailed
fixture definition and reproduction steps are in
[`research/isw21_r1cs_opening_smoke/README.md`](../research/isw21_r1cs_opening_smoke/README.md).

The smoke now has an experimental two-process path. The prover/setup process
exports a parameter-tagged fixed-width verifier-key file and an envelope with
the public primary input plus response; a second process loads only those
objects and verifies. The verification routine does not need the prover CRS
or KTX matrices. The key codec stores the LWE secret-key matrices, QAP
public-input prefixes and `Z_s`; it preserves the upstream ring components'
128-bit stored representation and uses canonical field-element bytes. The
key file is restricted to owner read/write permissions on POSIX (`0600`).
One real test generated a 2,419,872-byte verifier key and 23,907-byte
statement/response envelope, and a separate verifier process accepted it.
CTest passed honest verification, response tampering rejection, changed
context rejection, truncated proof/key rejection, and the key permission
check in two consecutive runs (`1/1` in 12.32 s, then `1/1` in 10.59 s).
The verifier interface now also requires its own expected 32-byte context;
it rejects absent context and replay under another expected context. The
prover can take a supplied 32-byte context, and a later CTest run generated
proofs for two different contexts, verified each in its own process, and
rejected cross-session reuse (`1/1` in 20.54 s). This checks interface
binding for the toy context bytes; it does not implement the target session
policy, same-session replay prevention, expiry, or normalized H.264 context
derivation. A follow-up run also rejected a proof under a verifier key from
another setup (`1/1` in 22.20 s).

This test also exposed an upstream undefined-behavior bug: QAP A/B/C prefix
vectors were `reserve()`d and then written through `begin()` without being
resized. The local research reproduction now applies both the tracked RNG
stream fix and [`upstream_qap_prefix_resize_fix.patch`](../research/isw21_r1cs_opening_smoke/upstream_qap_prefix_resize_fix.patch).
Neither patch is an upstream release or independent cryptographic audit.
The key/proof file codec has only been tested in separate processes in this
Linux container; cross-platform compatibility, setup authenticity, encrypted
key provisioning, and production use remain unverified.

The complete 23,907-byte experimental envelope was then carried through the
native H.264 Baseline/CAVLC path on one 704x576 Deadline-derived clip. The
blind extractor recovered all bytes from the video alone, and a separate
ISW21 verifier accepted the recovered bytes under the expected toy context.
There were 1,304 IDR and 70 P slices, zero SEI NALs, and 191,368 of 191,368
framed bits committed. Native encoding took 43.90 s; Python blind extraction
took 1,819.342 s for a 45.846 s clip. Full measurements and hashes are in
[`isw21_full_envelope_video_only_probe_20261001.md`](../benchmark/results/isw21_full_envelope_video_only_probe_20261001.md).
This is video-only transport plus toy-proof verification, not proof binding to
the received video's normalized context or a secure application relation.

## Rejected as a zero-knowledge backend: RoKoko (ePrint 2026/575)

RoKoko is not currently a viable backend for this zero-knowledge objective.
The reviewed paper establishes knowledge soundness for its argument, but the
paper/source reviewed here does not provide a zero-knowledge simulator or
theorem for the construction or its `snark` mode. The implementation's label
is not evidence of witness privacy; the final folded witness is verifier
readable. This is an unmet privacy property, not a proof that no separate
ZK composition could exist. Reconsider it only if a theorem-backed hiding
composition and exact implementation are supplied and independently reviewed.

The performance/size figures are still useful for transport comparison. The
paper reports a 112 KB proof at the smallest listed benchmark size
(`|Z_q| = 2^26`), with
1.47 s proving and 8.12 ms verification on the paper's target machine; these
are medians of three runs and exclude any video embed/extract work. The paper
states that the construction uses the vanishing-SIS (vSIS) assumption for
succinct verification. This is a distinct, less-established assumption path
than the standard Module-SIS route, so the paper's reduction and concrete
hardness estimate need independent review before the backend can be trusted.

The upstream repository is explicitly a proof-of-concept: it says the `snark`
mode is highly experimental and arbitrary-relation support is not fully
exposed. It pins Rust nightly `2025-03-06`, recommends AVX-512 for best
performance, and offers `incomplete-rexl` as a pure-Rust fallback. No RoKoko
build or runtime result is claimed locally; that is secondary to the missing
zero-knowledge guarantee.

The reported 112 KB proof is smaller than this repository's Ringo binary proof
(about 1.65 MB), but still does not fit the measured stable blind carrier
profile on the 300-frame Foreman CIF clip: 2,941 patchable carriers are only
about 368 bytes, so the paper proof alone is roughly 305 times larger before
statement/framing bytes. The clip-specific raw-safe upper bound was 101,842
bits (about 12.7 KB), also below 112 KB. This does not rule out a much longer
or higher-capacity video, but it means RoKoko's published proof size is not a
drop-in fit for the tested clip/profile. No current RoKoko artifact proves the
payload-opening/session/video-context relation, and its proof has not been
embedded or blindly extracted from H.264 in this project.

**Decision:** do not spend integration effort on RoKoko as a ZK backend unless
the zero-knowledge gap is resolved with a theorem-backed composition. Its
published proof size alone also exceeds the measured raw-safe capacity of the
300-frame Foreman CIF profile. An author write-up from September 2026 describes
a standard-SIS instantiation, but says that variant is not in the repository's
main code; it neither resolves the privacy gap nor counts as an available
backend.

## Screened alternatives: LaBRADOR and Practical Sublinear R1CS

LaBRADOR is a credible lattice-based R1CS *argument-of-knowledge* direction,
but the published implementation is not a drop-in ZK backend. Its paper
explicitly disables zero knowledge in its proof-size comparisons and leaves
the ZK property out of scope; it only observes that a linear-sized masking
shim could be composed later. The paper reports 49.02--53.84 KB for binary
R1CS instances from 2^20 through 2^25 constraints, before any such shim. Its
security analysis is based on Module-SIS with paper-estimated 128-bit
parameters, not an estimate for this application's circuit or commitment.
The authors' C implementation requires AVX-512 and its published test runs a
large polynomial-evaluation front end followed by recursive LaBRADOR, not
this application's proof relation. A separate Rust port currently documents
that only the core protocol is implemented and the binary/ring R1CS reductions
are still in progress. Thus LaBRADOR is useful as a size/performance
comparison, but neither candidate artifact currently demonstrates a
zero-knowledge proof of our application statement on the i7-12700H host.

The CRYPTO'22 paper *Practical Sublinear Proofs for R1CS from Lattices*
(ePrint 2022/1048) is explicitly zero knowledge and describes a
Fiat--Shamir non-interactive variant, but the paper's 128-bit-field example is
10.79 MB at 2^24 constraints. Its authors leave an implementation to future
work, and the interactive protocol/large-statement design does not provide a
ready implementation for this small application relation. It is therefore
not a practical short-term integration candidate either.

**Decision:** do not replace ISW21 with either candidate. The search so far
has not found a complete, locally runnable lattice implementation that
simultaneously supports the target relation, knowledge soundness under an
acceptable reviewed assumption, zero knowledge, independently provisioned
prover/verifier operation, and a proof size shown to fit the measured H.264
carrier. The next backend step remains a deliberately small application
relation plus an independently reviewable protocol/key lifecycle; do not
claim that choosing another published R1CS proof system closes these gaps.

## Remaining gates

- independently check the ISW21 security theorem and concrete parameter
  estimates for this exact circuit and designated-verifier setup, including
  the quantum attack against its knowledge-based LWE linear-only assumption,
  the stronger LTM route to knowledge soundness, the 40-bit statistical ZK
  parameter, and the non-reusable verification-oracle model;
- select a secure lattice commitment with concrete hiding/binding estimates;
  implement and independently review its bounded payload-opening relation,
  canonical context encoding and setup/key lifecycle, including verifier-key
  confidentiality;
- harden the experimental verifier-key/proof codecs, authenticate and protect
  designated-verifier key provisioning, and extend the toy statement envelope
  with the target session, registry, and normalized-video fields;
- reconcile the proof statement's sign-only trailing-one carrier profile with
  the native encoder's current magnitude-parity carrier (`abs(level) >= 5`),
  then test that both sides derive identical carrier positions and the same
  normalized-video digest; the encoder currently embeds during x264 encoding,
  so a digest computed from a preliminary encode is not yet shown invariant
  when the proof bits change;
- produce a real proof for the application relation, measure its exact bytes,
  and embed/extract it blindly from H.264 Baseline/CAVLC with no proof sidecar;
- run wrong-payload, changed-context, malformed-proof, tamper, replay, expiry,
  and cross-session negative tests through the actual verifier;
- do not use RoKoko as ZK unless its witness-privacy gap is resolved by a
  theorem-backed construction and the exact implementation is independently
  reviewed; and
- independently evaluate whether ePrint 2025/2099 has a complete matching
  implementation and whether its adaptive-knowledge-soundness theorem and
  MSIS parameters are preferable to RoKoko; and
- benchmark repeated setup/prove/verify time, peak RSS, visual quality, and
  carrier capacity on multiple real videos and durations.

## Source references

- [ISW21 paper: *Shorter and Faster Post-Quantum Designated-Verifier
  zkSNARKs from Lattices*](https://eprint.iacr.org/2021/977)
- [Upstream reference implementation and build instructions](https://github.com/lattice-based-zkSNARKs/lattice-zksnark)
- [Pinned upstream source revision](https://github.com/lattice-based-zkSNARKs/lattice-zksnark/tree/48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e)
- [LUNA, ePrint 2022/1690](https://eprint.iacr.org/2022/1690): later analysis of
  ISW21's knowledge-based LWE linear-only assumption, the weaker LTM route to
  argument soundness, and conditions required to recover knowledge soundness.
- [Ahmadi et al., *A Lattice-based Designated Verifier zkSNARK from Standard
  Assumptions*, ePrint 2025/2099](https://eprint.iacr.org/2025/2099): revised
  2026-07-13; full-paper claim is an MSIS-based DV-LatticeIPA with adaptive
  knowledge soundness via coordinate-wise special soundness in the random-
  oracle model, composed with an LPCP compiler.
- [Klooß et al., *RoKoko: Lattice-based Succinct Arguments, a Committed
  Refinement*, ePrint 2026/575](https://eprint.iacr.org/2026/575): the paper
  reports 112 KB proofs in its `2^26` benchmark and states its succinct
  construction relies on vSIS; these are paper results, not local
  application-pipeline measurements.
- [RoKoko upstream implementation](https://github.com/lattice-arguments/rokoko):
  README documents the experimental SNARK mode, nightly toolchain and
  incomplete pure-Rust backend.
- [Author's standard-SIS instantiation note](https://www.osdnk.me/blog/rokoko-standard-assumptions):
  describes a variant but says it was not in the repository's main branch at
  publication; it is not a primary security proof or code artifact.
- [Linked C implementation](https://github.com/crypolover1998/LatticeBased-Dv-zkSNARK/tree/9bc41a62cd901c360d87f49a708b93c12238b5b8): pinned source reviewed,
  but predates the paper and only simulates lambda=1 commitment/response work;
  it is not a complete implementation of the revised construction.
- [Only open pull request (#1)](https://github.com/crypolover1998/LatticeBased-Dv-zkSNARK/pull/1): README-only change; no newer prover/verifier source was found.
- [LUNA reference implementation](https://github.com/yassimert/LUNA): its
  README scopes the published code to the HGSW component and documents Linux,
  C++17/GCC, PALISADE, and a 32-GB-RAM recommendation for the Ng≈2^16 run.
- [Debris-Alazard, Fallahpour, Stehlé, ePrint 2024/030](https://eprint.iacr.org/2024/030):
  quantum oblivious sampling attack on the standard-model lattice-SNARK
  knowledge assumption discussed by LUNA.
- [LaZer upstream requirements](https://github.com/lazer-crypto/lazer): Linux
  x86-64 with AVX-512 and AES. The local i7-12700H's Intel product
  specification lists AVX2, not AVX-512, so LaZer is not a local runtime
  candidate without different hardware.
- [LaBRADOR paper, ePrint 2022/1341](https://eprint.iacr.org/2022/1341):
  Module-SIS R1CS argument; the paper explicitly leaves ZK out of scope and
  reports 49--54 KB for binary R1CS at 2^20--2^25 constraints.
- [LaBRADOR C implementation](https://github.com/lattice-dogs/labrador):
  research implementation requiring AVX-512; its README describes a
  polynomial-evaluation test rather than this application's R1CS.
- [LaBRADOR Rust port](https://github.com/lattirust/labrador): README states
  that binary/ring R1CS reductions are in progress.
- [Nguyen and Seiler, *Practical Sublinear Proofs for R1CS from Lattices*,
  ePrint 2022/1048](https://eprint.iacr.org/2022/1048): zero-knowledge R1CS
  protocol with a Fiat--Shamir variant; paper reports 10.79 MB at 2^24
  constraints for its 128-bit-field example and leaves implementation as
  future work.
