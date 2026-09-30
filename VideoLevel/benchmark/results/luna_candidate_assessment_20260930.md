# LUNA lattice-ZK candidate assessment (2026-09-30)

## Decision

LUNA is a mathematically relevant lattice-ZK protocol candidate, but the
available upstream repository is **not a LUNA prover/verifier implementation**
and is not an integration-ready backend for this project. Do not treat the
paper's small proof-size result as measured proof output for the video
relation. Keep LUNA as a protocol-level candidate only; prioritize a backend
whose complete protocol implementation, application relation, serialization,
and soundness/privacy properties can be exercised and reviewed together.

## What the paper establishes

The authors describe LUNA as a designated-verifier lattice-based ZK-SNARG.
Their Theorem 5 gives a ZK-SNARG under statistical soundness of the LPCP,
IND-CPA security and strict linear-only targeted malleability of HGSW; the
zero-knowledge conclusion additionally requires an honest-verifier ZK LPCP
and statistical circuit privacy of HGSW. The result has non-adaptive
soundness. Theorem 6 upgrades this to a ZK-SNARK/argument of knowledge under
stronger conditions: computationally simulatable strict LTM and knowledge
soundness of the LPCP; this result is also non-adaptive.

Table 1 reports a 5.8 KB proof for an R1CS with `Ng = 2^16` at the paper's
stated 128-bit soundness/privacy setting. Separately, the HGSW implementation
section reports 6.93 KB for its chosen fixed parameters (used across
`Ng <= 2^20`). Neither number is a measured payload-opening proof or a
serialized artifact produced by this project's code. The same table reports
CRS sizes of 1.25 GB (compressed) and 18 GB (full), so
setup/provisioning is also substantial. Against current 300-frame
raw candidate scans, Coastguard has an upper bound of 76,550 bits (~9.57 KB)
and Akiyo 29,847 bits (~3.73 KB). Thus the paper's 5.8 KB point is below
Coastguard's *raw* ceiling and above Akiyo's, but this is not evidence that
either carrier can embed it: these scans have zero confirmed patchable bits,
and do not include a LUNA proof or validated video framing. The source data
are `ringo_blind_stable_capacity_coastguard_300f_20260930.json` and
`ringo_blind_stable_capacity_akiyo_300f_fallback_20260930.json`.

## Implementation and host evidence

The [official implementation repository](https://github.com/yassimert/LUNA)
states that it implements the HGSW vector-encryption primitive used by LUNA.
Its published file tree contains HGSW setup/encrypt/add/decrypt code and a
primitive test driver, not the complete LPCP/SNARG/SNARK setup, prover,
verifier, proof serializer, or application circuit. The paper's evaluation
section likewise describes experimental results for the HGSW implementation,
not the complete LUNA proof protocol. For `Ng = 2^16`, it reports HGSW-only
`Setup+Encrypt` 159 s, `Add` 21.51 s, and `Decrypt` 0.0007 s; the paper maps
these roughly to protocol setup/prove/verify components but explicitly
excludes LPCP runtime. These are paper timings on its stated Linux Xeon E-2314
/ 128 GB host, not measurements on this system.

The upstream README requires Linux, AES-capable CPU, CMake, GCC/G++, and
PALISADE; it warns that the `Ng ~= 2^16` HGSW experiment may need about 20 GB
RAM. The current host has no usable Linux build environment in this worktree
and the official implementation does not supply an end-to-end protocol to
run even if the HGSW primitive were built. No LUNA source was cloned or
modified, and no proof/performance result was generated in this assessment.

## Relevance to this system and remaining gates

- The designated-verifier model can support an independent verifier that
  keeps verification state private, but it is not public verification; setup,
  verifier-state provisioning, and session-policy binding would need explicit
  design and review.
- The system's target relation must prove knowledge of a valid payload opening
  and bind the canonical video/session context. The LUNA paper's generic R1CS
  result does not compile or establish that application-specific statement.
- The paper's non-adaptive security result must be checked against the actual
  setup/statement lifecycle. It is not enough to rely on the paper's protocol
  label or the small generic proof-size point.
- The full protocol implementation, exact parameter set, complete proof bytes,
  context-bound transcript, verifier API, rejection tests, and H.264 blind
  embedding/extraction are all absent from the available repository.

## Sources

- [LUNA paper, IACR ePrint 2022/1690](https://eprint.iacr.org/2022/1690.pdf)
  (Theorems 5–6 and Table 1)
- [Official LUNA source repository](https://github.com/yassimert/LUNA)
- [ACM CCS 2024 publication record](https://doi.org/10.1145/3658644.3670345)
