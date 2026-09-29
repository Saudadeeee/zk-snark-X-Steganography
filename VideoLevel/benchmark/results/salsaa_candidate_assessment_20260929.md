# SALSAA candidate assessment (2026-09-29)

## Decision

**Revisit as a research candidate; do not integrate or advertise as this
system's lattice ZK backend.** SALSAA is materially more relevant than
linear-relation-only prototypes because the paper reports native R1CS support.
However, the current evidence does not establish zero knowledge for the
concrete implementation, the required video/payload relation, or fit in the
measured in-video carrier.

This is a source-based assessment only. SALSAA was not cloned, built, run, or
modified in this assessment.

## Primary-source evidence

- The [IACR ePrint record](https://eprint.iacr.org/2025/2124) identifies the
  paper as a preprint, last revised 2026-08-25. Its abstract says SALSAA
  supports R1CS and reports a lattice succinct argument of knowledge with
  41 ms verification, 10.61 s proving, and a 979 KB proof for a witness of
  `2^28` `Z_q` elements. It separately reports a folding proof of 73 KB and
  2.28 ms verification. The 73 KB figure is for the folding scheme, not the
  standalone R1CS argument, so it cannot be treated as the proof size for this
  application's relation.
- The [official implementation README](https://github.com/lattice-arguments/salsaa)
  describes the repository as auxiliary material implementing SALSAA and its
  SNARK/PCS and folding applications. It documents nightly Rust, GCC, CMake,
  Intel HEXL, and an AVX2 fallback when AVX-512 is unavailable. Its run command
  selects a parameter-feature executable; the README does not document a
  stable application-facing API or an H.264/video relation frontend.
- The abstract names an “argument of knowledge”; that wording alone does not
  establish a zero-knowledge property. The paper PDF could not be retrieved in
  this review, so the precise ZK theorem and whether it covers the implemented
  concrete protocol remain unresolved. This is **not** evidence that SALSAA
  lacks ZK; it is a gate that has not yet been passed.
- No independent security audit artifact was located in the inspected primary
  sources. This is a search result, not proof that no review exists.

## Capacity comparison: evidence versus inference

The local measured capacity artifact
`benchmark/results/sec2_capacity_data.json` records Akiyo Q22/GOP1 with
`operating_bits=1232` (154 bytes), `patchable_usable_bits=2000`, and
`validated_pool_bits=1449`. These values apply to that tested sample/profile,
not to every possible video.

The paper's 979 KB reported argument is orders of magnitude larger than the
1,232-bit operating carrier for this sample (approximately 6.4 thousand times
larger using decimal KB). This is a cross-source scale comparison, not a local
measurement. The paper's witness size is not the same as the application's
relation, so it does **not** prove that every SALSAA proof configuration is too
large. It does establish that current evidence cannot support a claim of fit.
The separate 73 KB folding result is also much larger and is not a substitute
for the required application proof.

## Unresolved adoption gates

1. Inspect the full paper's exact zero-knowledge theorem, simulator and
   composition conditions; map those conditions to the shipped implementation.
2. Derive the concrete security level, soundness error, Fiat-Shamir model and
   parameter estimator output for an exact verifier-pinned R1CS relation.
3. Encode the context-bound payload-opening relation and bind verifier-derived
   codec policy, challenge, carrier schedule and non-circular video commitment.
4. Determine whether the proof has a canonical stable serialization and whether
   all bytes fit in the actual quality-validated carrier. Measure, do not infer.
5. Only after those source-level gates, build an isolated reproducible PoC and
   run blind extraction/verification and negative tests against real H.264.

R1CS support is a promising route to expressing application constraints; it
does not itself instantiate the required relation, guarantee ZK, or solve the
carrier-capacity problem. Until all gates are passed, SALSAA remains a
candidate and the overall system goal remains incomplete.
