# LatticeFold candidate assessment (2026-09-30)

## Decision

LatticeFold is a promising lattice-based folding component, but the inspected
upstream project is **not a ready standalone lattice-ZK prover/verifier for
this application**. Keep it as a research candidate; do not switch the public
video API to it or treat its example proof as an application ZK proof.

## Protocol versus the available code

The [LatticeFold paper](https://eprint.iacr.org/2024/257) presents a lattice
folding scheme and discusses its use inside succinct proof systems. It notes
that a final SNARK proof can be made zero knowledge. That is not the same as
showing that an arbitrary intermediate folding transcript or every code
example is a complete ZK proof.

The [upstream repository at the inspected revision](https://github.com/NethermindEth/latticefold/tree/15cc045c18ea92a50c23528d1e7b62dd392b8c42)
describes itself as a proof-of-concept implementation, explicitly says it has
not received careful code review and is not production-ready, and lists the
main crate as a non-interactive folding scheme with Ajtai commitments,
R1CS/CCS structures, and Fiat-Shamir transcript machinery. `latticefold-plus`
is marked work-in-progress. The repository advertises R1CS/CCS as circuit
frontends, but that alone does not provide a complete zero-knowledge SNARK
composition for a deployed application.

The sole documented `e2e.rs` example constructs a test/dummy CCS instance,
uses `ark_std::test_rng()`, runs an NIFS fold prover and verifier, and
serializes the resulting fold proof through `ark_serialize`. It demonstrates
that a fold proof object can be serialized and verified; it does not show the
final succinct-proof composition, a reviewed ZK simulator/property for this
application statement, the payload-commitment opening, session/video binding,
or H.264 transport. Its source also uses generated small example parameters,
not the project's application relation.

## Execution evidence on this host

No Rust toolchain is available on the current host: `cargo`, `rustc`, and
`rustup` are absent from PATH, and the conventional per-user Cargo/toolchain
locations are absent. LatticeFold was not cloned, built, or run; no proof bytes
or performance measurements were produced in this review. This avoids
mistaking the repository's proof-of-concept claims or paper estimates for
local results.

## Application gates

- Identify and pin the exact **complete final ZK proof composition**, including
  the security theorem and assumptions that make the final proof hide the
  witness; do not stop at one NIFS fold.
- Encode the actual relation: knowledge of a payload and opening for the
  verifier-pinned commitment, plus canonical session and normalized-video
  context. The available fold example does not contain this relation.
- Establish canonical Fiat-Shamir context binding and verifier policy with an
  independent security review.
- Produce an actual serialized proof, then measure whether blind-stable,
  patchable CAVLC positions can carry it without SEI or a sidecar.
- Run tamper/replay/wrong-session/expiry tests and real-video quality,
  resource, proving-time, and verification-latency measurements.

## Conclusion

LatticeFold may be an ingredient in a future lattice SNARK stack, and the
paper's final-proof discussion makes it worth retaining as a research lead.
The currently published code does not remove the central project blocker:
there is still no integrated, reviewed, serializable lattice-ZK proof for the
required payload-opening/video/session relation. The public APIs should remain
fail-closed until that complete path exists.
