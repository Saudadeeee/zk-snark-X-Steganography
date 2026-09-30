# Symphony lattice-SNARK candidate assessment (2026-09-30)

## Decision

Symphony is a worthwhile *paper-level architecture* to track, but the current
public evidence does not make it an implementation-ready, zero-knowledge
backend for this project. Do not enable it or relax the public APIs' fail-closed
behavior. The paper explicitly leaves its concrete instantiation for future
work; its stated SNARK definition proves completeness, succinctness, and
knowledge soundness, but does not state a zero-knowledge property. A suitable
ZK commit-and-prove/SNARK composition would still need to be selected, proved,
implemented, and measured.

## Primary-source findings

The IACR ePrint record identifies the latest version as a minor revision of an
ASIACRYPT 2026 publication. Its abstract describes Symphony as a framework
using folding as a black box in the random-oracle model, with a new lattice
high-arity folding component. The authors describe the post-quantum status as
plausible, not as a concrete-system certification.

The paper's Definition 2.7 defines a SNARK through completeness, succinctness,
and knowledge soundness. Theorem 6.1 and Corollary 6.2 establish a SNARK
construction from a folding reduction and two SNARK components; these stated
properties do not themselves establish hiding of this application's payload
or commitment opening. The CP-SNARK definition checks knowledge of a witness
opening a commitment, but that syntax alone does not make the proof zero
knowledge. An implementation must instantiate both proof components with
adequate ZK guarantees and show that the combined transcript preserves them.

Section 7 says the concrete implementation is future work and gives estimates,
not measured benchmark results. Its candidate parameters are described as
117-bit MSIS security. For one lattice-based instantiation the paper estimates
proof size below 200 KB (using component proof sizes in the 50–100 KB range),
and flags verifier work on roughly 1 MB of Fiat–Shamir randomness as an open
cost. These are paper estimates, not serialized proof measurements or a
project-specific security evaluation. The official author's page links the
Nethermind repository under the LatticeFold entry; that link is not evidence of
a Symphony implementation. The accessible paper's 2026 Syscoin bibliography
entry says “Implementation and Applications of Symphony” but gives only a
placeholder `link`; no reproducible, official implementation artifact was
located in this review.

## Carrier fit against current measurements

The current blind-stable raw scans provide only upper bounds, not verified
patchable capacity: Coastguard 300-frame has 76,550 bits (9,568 bytes), and
Akiyo 300-frame has 29,847 bits (3,731 bytes). The measured runs did not
confirm those candidates as patchable H.264 carriers. Compared with the
paper's `<200 KB` candidate proof estimate, even the Coastguard raw ceiling is
at least about 20.9× too small and Akiyo about 53.7× too small, before adding
an in-band envelope, session/context binding, framing, or error recovery. A
longer clip may increase capacity, but that has not been established as a
viable or quality-preserving operating point; the current data do not prove
this architecture fits.

## Project integration gates

Before reconsidering Symphony, require all of the following:

1. Obtain a version-pinned, publicly inspectable implementation of the complete
   folding-to-SNARK construction and its dependencies, not only a folding
   component or application announcement.
2. Independently audit the exact security theorem/assumptions and show a
   zero-knowledge composition for the payload-opening relation. Bind the
   verifier-issued session challenge, expiry/nonce, commitment, canonical
   video context, and declared public policy as public inputs.
3. Build and run prover/verifier tests on this host or a pinned supported
   environment; retain serialized proof bytes, CPU/RAM/time, reproducible
   commands, and dependency commit hashes.
4. Serialize the complete proof into the existing H.264 Baseline/CAVLC
   residual carrier with no SEI or sidecar; prove blind extraction and test
   tamper, replay, wrong-session, and expiry rejection.
5. Measure patchable capacity and per-frame quality on real videos. The
   current raw-capacity ceilings are already far below the paper estimate, so
   the carrier-size gate must be demonstrated rather than inferred from
   succinctness claims.

Until these gates pass, Symphony is research input only. The source assessment
does not change the implementation or its fail-closed API behavior.

## Sources

- [IACR ePrint 2025/1905, paper and revision metadata](https://eprint.iacr.org/2025/1905)
- [Full paper PDF, especially Definitions 2.7–2.8, Theorem 6.1, and Section 7](https://eprint.iacr.org/2025/1905.pdf)
- [Author's research page](https://chancharles92.github.io/)
- [Nethermind LatticeFold repository](https://github.com/NethermindEth/latticefold) — linked under the author's separate LatticeFold entry, not identified as Symphony code.
- `benchmark/results/ringo_opening_proof_wire_recheck_20260930.md` — local raw-capacity and patchability caveats.
