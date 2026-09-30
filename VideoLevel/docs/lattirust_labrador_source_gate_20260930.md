# Lattirust LaBRADOR source gate recheck (2026-09-30)

## Decision

Keep `lattirust/labrador` as a **research candidate only**. Do not claim it is
integrated, production-ready, or currently proves this application's target
relation. This is not a finding that the LaBRADOR paper's protocol is
unsound; the gate is that the inspected implementation is incomplete for the
required statement/relation, has not been independently reviewed, and did
not build/test cleanly as unmodified upstream on this host.

## Pinned source and reproducibility

The upstream default branch was inspected at commit
[`024c48e49025765ef3a7c08889b2d2fc61de0612`](https://github.com/lattirust/labrador/commit/024c48e49025765ef3a7c08889b2d2fc61de0612)
(2025-04-22). The README describes the core LaBRADOR protocol as implemented,
but says the reductions from binary and ring R1CS are still in progress. It
directs users to `cargo test` and cites the LaBRADOR paper, *Compact Proofs
for R1CS from Module-SIS*.

The source was fetched from the pinned GitHub revision and inspected for
transcript binding, incomplete code paths, and tests. Initially the host had
Python 3.12.10 but no `cargo`, `rustc`, or `rustup`. A temporary, isolated
nightly-2025-03-10 GNU toolchain was then installed under the OS temp folder;
the repository worktree and system PATH were not changed. The repository was
cloned at the pinned commit into that temp folder.

The unmodified upstream `cargo test --locked` did not build: the dependency
`lattice-estimator`'s `build.rs` invokes Unix `sage` and `env` commands, and
the host has no SageMath. For diagnosis only, the build script in Cargo's
temporary Git checkout was replaced with a no-op. Its manifest has PyO3
commented out, so the Rust sources could be compiled without that optional
Python path; **this is not an unmodified upstream build**. No project source
or pinned cryptographic/prover source was modified. No proof was generated
and no performance benchmark was performed.

With only that temporary build-script workaround, the upstream Rust crate
compiled, but `cargo test --locked` reported **1 passed, 3 failed**:

- `binary_r1cs::test::test_soundness` passed.
- `binary_r1cs::test::test_completeness` failed because the reduction output
  witness did not satisfy the generated principal-relation constraints. The
  isolated command `cargo test --locked
  binary_r1cs::test::test_completeness -- --nocapture` reproduced the failure
  (0 passed, 1 failed); the diagnostic lists many unsatisfied standard and
  constant-coefficient constraints.
- `test::test_completeness` and `test::test_soundness` both failed when the
  runtime lattice estimator attempted to invoke unavailable SageMath.

Thus there is now direct test evidence that the pinned binary-R1CS reduction
does not satisfy its own completeness test under the configured test. This
is stronger than a TODO/source-only concern, but it still does not identify
the mathematical root cause or prove a soundness exploit. The one passing
soundness test does not compensate for failed completeness or establish
application security.

## Findings

1. **Application statement binding is not enforced by the library entry
   points.** In the pinned binary-R1CS prover,
   [`prove_reduction_binaryr1cs_labradorpr`](https://github.com/lattirust/labrador/blob/024c48e49025765ef3a7c08889b2d2fc61de0612/src/binary_r1cs/prover.rs#L27-L50)
   accepts the index and instance but has `TODO: add statement to merlin`
   before deriving challenges. In the matching
   [verifier](https://github.com/lattirust/labrador/blob/024c48e49025765ef3a7c08889b2d2fc61de0612/src/binary_r1cs/verifier.rs#L69-L89),
   `verify_binary_r1cs` has `TODO: add crs and statement to transcript`.
   Therefore callers must not assume the library automatically binds
   `session_challenge`, normalized-video commitment, carrier profile,
   commitment, relation ID, or parameters into Fiat–Shamir. A carefully
   specified outer transcript initialization might supply some bindings, but
   this repository has no such wrapper and that composition has not been
   reviewed. The TODO is evidence of a missing library guarantee, **not by
   itself evidence of an exploitable forgery**.

2. **The general ring-R1CS path is visibly incomplete.** The pinned
   [`src/r1cs/prover.rs`](https://github.com/lattirust/labrador/blob/024c48e49025765ef3a7c08889b2d2fc61de0612/src/r1cs/prover.rs#L21-L94)
   contains `todo!()` at the encoding and protocol stages; the pinned
   [`src/r1cs/verifier.rs`](https://github.com/lattirust/labrador/blob/024c48e49025765ef3a7c08889b2d2fc61de0612/src/r1cs/verifier.rs)
   is empty. The API cannot currently be treated as a complete generic R1CS
   prover/verifier implementation.

3. **The included binary-R1CS tests are not application integration tests.**
   [`src/binary_r1cs/test.rs`](https://github.com/lattirust/labrador/blob/024c48e49025765ef3a7c08889b2d2fc61de0612/src/binary_r1cs/test.rs)
   invokes generic completeness/soundness test macros for a small test
   relation. The test source does not encode this project's payload opening,
   video/session statement, H.264 transport, or replay policy.

4. **The required app relation is still absent.** The project target requires
   proving knowledge of a bounded payload opening for the public commitment
   and binding the canonical statement described in
   [`LATTICE_VIDEO_ZKP_RELATION_v0.1.md`](LATTICE_VIDEO_ZKP_RELATION_v0.1.md).
   Upstream source inspection did not find that circuit/relation, a project
   parameter set, a verifier-pinned transcript wrapper, or a serialized
   proof envelope integrated with CAVLC. The paper's general R1CS capability
   is not evidence that this specific relation has been compiled, proven,
   reviewed, or fits available carriers.

5. **Audit status remains a separate gate.** Lattirust describes itself as
   research/prototyping software and not audited; passing repository tests
   would not replace cryptographic review of the exact implementation,
   transcript composition, relation encoding, and parameters.

## Next evidence required

- Fix and independently review the binary-R1CS completeness failure; rerun
  the full tests without the temporary build-script workaround and with a
  functioning pinned lattice estimator.
- Make the upstream build/test path reproducible on the target platform, or
  select and document a supported Linux build environment with SageMath.
- Complete the chosen R1CS reduction and verifier; define a canonical
  transcript that binds the complete public instance, CRS/parameters, and
  protocol/domain IDs before challenge derivation.
- Implement the bounded payload-opening relation and test wrong commitment,
  context substitution, malformed witness/range, and cross-session replay
  rejection against the verifier.
- Obtain independent review of the exact relation, transcript, assumptions,
  parameters, and implementation before making a security claim.
- Measure actual serialized proof size and prove complete blind extraction
  from H.264 CAVLC without SEI or proof sidecar; then run the broader quality,
  resource, latency, and tamper benchmark gates.

## Alternative repository recheck: lattice-complete/Lazarus

The public `lattice-complete/Lazarus` repository was inspected as a possible
Rust alternative that would not depend on LaZer's AVX-512 toolkit. Its own
README explicitly warns that it is under active development and must not be
used in production. It advertises lattice proofs, but gives no actionable
getting-started dependency/example; its displayed benchmark table does not
provide a pinned commit, relation definition, raw output, or reproduction
command. These headline numbers are not accepted as evidence for this
project's proof size or performance.

The current LaBRADOR composite source also defines `CompositeProof` with a
`final_witness` field, describes that value as an in-clear witness, and passes
it to the reduced-statement verifier. This observation is not by itself a
proof-system break: the recursive reduction may transform/randomize the
witness. It is, however, a concrete privacy-review obligation before mapping
the application payload-opening secret into this API. No Lazarus source was
built or executed in this recheck; no security conclusion or integration claim
is made.

Sources inspected: [Lazarus repository README](https://github.com/lattice-complete/Lazarus#readme),
[composite proof structure and prover](https://github.com/lattice-complete/Lazarus/blob/main/labrador/src/composite.rs#L378-L495),
and [composite verifier](https://github.com/lattice-complete/Lazarus/blob/main/labrador/src/composite.rs#L499-L528).

## Sources

- [Pinned Lattirust LaBRADOR repository](https://github.com/lattirust/labrador/tree/024c48e49025765ef3a7c08889b2d2fc61de0612)
- [LaBRADOR paper, IACR ePrint 2022/1341](https://eprint.iacr.org/2022/1341)
- [Lattirust security statement](https://github.com/lattirust/lattirust#security)
