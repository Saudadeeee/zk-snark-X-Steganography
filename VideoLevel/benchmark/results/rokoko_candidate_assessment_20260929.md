# RoKoko candidate assessment and ZK gate recheck (2026-09-30)

## Decision

**Reject RoKoko as-is for the required zero-knowledge backend.** The complete
paper is now available and was inspected. Its formal security development
defines reductions of knowledge and knowledge soundness, but this review found
no zero-knowledge definition, simulator, or theorem for the construction or
the implementation's `snark` mode. This is an absence of a justified ZK claim,
not a proof that no separate ZK transformation is possible. The code still
labels the `snark` frontend highly experimental. It also lacks this project's
video/payload relation and an application-specific proof that fits the blind
H.264 carrier. Preserve only as a research lead if authors provide a
theorem-backed privacy composition; do not integrate or advertise as ZK now.

The 2026-09-29 assessment was source/documentation-only. On 2026-09-30 the
official ePrint PDF was retrieved and text-extracted locally; no RoKoko code
was cloned, built, run, or modified. The repository was source-inspected at
pinned commit [`6298afe840e80c4d1e10e78e6ee6f93e4cc31531`](https://github.com/lattice-arguments/rokoko/tree/6298afe840e80c4d1e10e78e6ee6f93e4cc31531).

## Primary-source evidence

- The authors' [RoKoko paper record](https://eprint.iacr.org/2026/575), mirrored
  on [King's College London Pure](https://kclpure.kcl.ac.uk/portal/en/publications/rokoko-lattice-based-succinct-arguments-a-committed-refinement/), dates
  the preprint to 2026-09-09. Its abstract describes a lattice-based succinct
  argument with a linear-time prover and polylogarithmic communication and
  verification. It supports tensor-structured relations, including polynomial
  evaluation and sumcheck relations. The full paper reports a 112 KB PCS proof
  for 2^26 coefficients, with 3.38 s commit+prove and 8.12 ms verification on
  its benchmark host. These are paper results for its PCS experiment, not for
  this application's relation or hardware.
- The [official Rust implementation](https://github.com/lattice-arguments/rokoko/tree/6298afe840e80c4d1e10e78e6ee6f93e4cc31531)
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
- The full [official ePrint paper PDF](https://eprint.iacr.org/2026/575.pdf)
  was retrieved via the IACR URL after the browser fetch returned 403 and
  inspected with local PDF text extraction. The paper formalizes a reduction
  of knowledge and a knowledge-soundness property (Definition 3); the full-text
  review found no zero-knowledge definition, simulator, or ZK theorem for
  RoKoko. Its abstract describes a succinct argument system, not a ZK theorem.
  The code's label `snark` is not evidence of witness privacy. This review did
  not prove the protocol is non-ZK or rule out a separate transformation; it
  establishes that the inspected paper/code do not justify the ZK claim needed
  here. The paper discusses shrinking a witness until it can be sent in the
  clear as a general design goal; the frontend guide also says the verifier
  reads the final folded witness. No hiding theorem for that value was found.
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

1. Do not use current RoKoko as ZK. Any reconsideration first requires an
   author-specified, theorem-backed ZK composition and an independent review
   that accounts for the verifier-readable folded witness.
2. Only after that gate, trace the implementation's `snark` feature to the
   paper's full protocol and determine exactly how hiding is achieved.
3. Derive the exact custom claim system for the repository's canonical
   video-bound opening relation and verifier-pinned statements.
4. Collect proof-size diagnostics for the smallest sound parameters and compare
   with measured in-band capacity. If the serialized proof cannot fit, do not
   integrate it as the target backend.
5. Only after these gates, build an isolated reproducible proof/verify trial,
   then attempt H.264 embed, video-only extraction, standard-decoder checks and
   negative tests.

RoKoko is rejected as-is for the active ZK requirement, not declared
impossible to transform. The overall system goal remains incomplete.
