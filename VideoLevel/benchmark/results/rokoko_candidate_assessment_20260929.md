# RoKoko candidate assessment (2026-09-29)

## Decision

**Prioritize for further paper/source review, but do not integrate yet.** RoKoko
is a newer lattice-argument implementation with an experimental SNARK frontend
and a composable sumcheck claim API. That makes it a more immediate integration
lead than the earlier SALSAA demo. The checked evidence still does not establish
zero knowledge for its concrete SNARK mode, the exact video/payload relation,
or a proof that fits this repository's validated carrier.

This is a primary-source/documentation review only. RoKoko was not cloned,
built, run, or modified in this assessment.

## Primary-source evidence

- The authors' [RoKoko paper record](https://eprint.iacr.org/2026/575), mirrored
  on [King's College London Pure](https://kclpure.kcl.ac.uk/portal/en/publications/rokoko-lattice-based-succinct-arguments-a-committed-refinement/), dates
  the preprint to 2026-09-09. Its abstract describes a lattice-based succinct
  argument with a linear-time prover and polylogarithmic communication and
  verification. It supports tensor-structured relations, including polynomial
  evaluation and sumcheck relations. The visible abstract's concrete proof-size
  values are stripped by the repository mirror, so this report does not infer
  or quote an exact RoKoko size.
- The [official Rust implementation](https://github.com/lattice-arguments/rokoko)
  calls itself a SNARK/PCS implementation and documents a pure-Rust arithmetic
  backend (`incomplete-rexl`) as well as Intel HEXL bindings. It says the pure
  Rust path runs on any Rust-supported platform with degraded performance;
  best performance requires AVX-512. Thus it is not evidently blocked by the
  project's AVX-512-missing host for correctness, but host execution and
  performance remain untested.
- Crucially, the implementation README explicitly labels the `snark` feature
  “highly experimental.” The [SNARK frontend guide](https://github.com/lattice-arguments/rokoko/blob/main/docs/snark.md)
  exposes a claim language over a committed vector and an example `prove_claims`
  flow. It also warns that the application author must correctly state and
  bind all relation claims. No H.264 parser, payload-opening circuit, blind
  extraction logic, or video commitment relation is documented there.
- The paper PDF was inaccessible in this review. The inspected abstract
  and README do not establish a formal zero-knowledge theorem for the concrete
  `snark` mode or its implementation; no theorem number, simulator, extraction
  argument, Fiat-Shamir security model or soundness error could be checked.
  This is an unresolved acceptance gate, not a claim that the protocol has no
  ZK property.
- The official [SNARK frontend guide](https://github.com/lattice-arguments/rokoko/blob/main/docs/snark.md)
  describes weighted-sum claims over pointwise products of a committed
  ring-element witness vector, with at most degree three per variable. It says
  relations between distinct indices require explicit witness layout and copy
  claims; this is not a general R1CS frontend. It also states that prover-shipped
  values need application-side structure checks. The guide's final-chain
  description says the folded witness is reduced until the verifier can read
  it in full. That is a ZK review red flag, not by itself proof of a ZK failure;
  the missing paper theorem and implementation mapping must resolve it.
- A coauthor's [RoKoko under Standard Assumptions write-up](https://www.osdnk.me/blog/rokoko-standard-assumptions)
  reports polynomial-opening proof sizes of 106.70–115.58 KB for parameter
  sizes `2^22`–`2^30` (30-bit `Z_q` elements), with prover times 0.300–9.392 s
  for the original vSIS variant and 0.293–8.983 s for the SIS variant. These
  are author-reported polynomial-opening benchmarks, not measurements of this
  project's relation; the SIS parameter variant is explicitly not yet in the
  main RoKoko branch.
- The README describes benchmarking on an Intel i7-11850H/64 GB system and
  larger parameter runs on Xeon Platinum 8468. Those are not measurements on
  this project's host. It also explains how to collect per-phase tracing and
  proof-size diagnostics; no local measurement was made here.

## Application and capacity gates

The local Akiyo Q22/GOP1 measurement is 1,232 operating bits (154 bytes),
2,000 patchable bits and 1,449 validated-pool bits in
`benchmark/results/sec2_capacity_data.json`. This is a measured result for one
tested profile, not a universal video limit.

The smallest cited 106.70 KB proof is approximately 693 times the 154-byte
operating carrier (using decimal KB). This is a cross-source scale comparison,
not an application benchmark or universal impossibility result. The current
sources provide no serialized proof size for the exact video relation and no
evidence it fits those 1,232 operating bits. The claim frontend appears capable
of expressing structured sumcheck claims, but the application must still
implement verifier-pinned constraints for payload
opening, context/session, codec policy, canonical video binding and carrier
framing. A generic claim API is not itself those constraints, and the
frontend's experimental status prevents treating a successful demo as a secure
integration.

The same Akiyo artifact's `raw_safe_bits=413415` corresponds to at most about
51.7 KB of raw candidate sign positions under that scan. At the reported
106.70 KB polynomial-opening size, proof bytes alone are about 2.06 times this
raw candidate pool, before envelope framing or any quality/reliability margin.
This is still a cross-source calculation and only applies to this measured
clip/scan; it does show that the published smallest proof point cannot fit
inside the project's currently enumerated Akiyo candidate pool without a
different carrier/codec strategy or a substantially smaller proof.

## Next review gates

1. Obtain and inspect the full paper for theorem statements, ZK definition,
   reduction assumptions, soundness error, Fiat-Shamir model and concrete
   parameter/security estimates.
2. Trace how the implementation's `snark` feature maps to the paper's complete
   protocol and determine whether witness hiding is guaranteed or must be
   added via commitments/randomization.
3. Derive the exact custom claim system for the repository's canonical
   video-bound opening relation and verifier-pinned statements.
4. Collect proof-size diagnostics for the smallest sound parameters and compare
   with measured in-band capacity. If the serialized proof cannot fit, do not
   integrate it as the target backend.
5. Only after these gates, build an isolated reproducible proof/verify trial,
   then attempt H.264 embed, video-only extraction, standard-decoder checks and
   negative tests.

RoKoko is a higher-priority lead to investigate, not an accepted backend. The
overall system goal remains incomplete.
