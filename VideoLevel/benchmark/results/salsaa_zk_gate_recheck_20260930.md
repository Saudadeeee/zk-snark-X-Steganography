# SALSAA zero-knowledge gate recheck (2026-09-30)

## Decision

**Do not use the inspected SALSAA implementation as this system's ZK backend.**
This is stronger than the 2026-09-29 assessment, which could not obtain the
paper PDF and therefore left its zero-knowledge property unresolved. The full
48-page ePrint paper was retrieved read-only and reviewed alongside the
official implementation source and README. In the construction described by
the paper, the cited security results are correctness and knowledge
soundness—not a zero-knowledge theorem—and the prover sends the final folded
witness to the verifier in the clear. No simulator, witness-indistinguishability
claim, hiding wrapper, or transcript blinding layer for that witness was found
in the reviewed construction.

This does **not** claim that no separate transformation could make SALSAA
zero-knowledge. It means the current paper/source pair does not justify the
privacy property required by this application. Adding a masking/commitment layer
would define a new protocol and require its own proof-size, soundness, privacy,
and implementation review; it cannot be assumed free or secure.

## Evidence inspected

- Official paper: [SALSAA, IACR ePrint 2025/2124](https://eprint.iacr.org/2025/2124),
  revision dated 2026-08-25. The paper was downloaded from its official PDF
  URL and text-extracted locally for review (48 pages; the temporary copy was
  not added to the repository).
- Theorem 5.1 states overwhelming correctness and negligible knowledge
  soundness for the composed argument under the listed vSIS assumptions and
  parameter conditions. It does not state zero knowledge or provide a
  simulator.
- Section 5.3 describes the final stage: after the witness height is reduced
  to O(1), the prover sends the remaining witness in the clear. This is an
  explicit privacy exposure in the protocol as written; calling its driver
  `SNARK` does not establish the `ZK` property needed here.
- The implementation's [`src/protocol.rs`](https://github.com/lattice-arguments/salsaa/blob/main/src/protocol.rs)
  is an experimental benchmark driver for sampled short witnesses and
  parameterized protocols, not a prover/verifier integration for this
  repository's payload-opening/video-session statement or its H.264 channel.
- The official [README](https://github.com/lattice-arguments/salsaa) documents
  an AVX2 fallback, nightly Rust, GCC, CMake, and Intel HEXL. These facts make
  a CPU build plausible but do not address the missing ZK property.
- The paper reports 979 KB for one general argument at witness size
  2^28 Z_q elements and 73 KB for a separate folding scheme. Neither number is
  a measurement for this app relation, a serialized video envelope, nor proof
  that the fold is zero-knowledge. Existing H.264 capacity measurements remain
  content/profile-specific and have not been rerun with SALSAA.

## Scope and consequence

The review was a theorem/source-level gate, not an independent external
cryptographic audit and not a local build. No code was added and no SALSAA
proof was generated or embedded. The candidate is now dispositioned as
**rejected as-is for a zero-knowledge claim; reconsider only with a separately
specified and reviewed privacy transformation**. This does not change the
system's active acceptance criteria: a reviewed lattice-ZK backend, complete
video-only transport, application relation, session policy, negative tests,
and representative measured benchmarks are still absent.
