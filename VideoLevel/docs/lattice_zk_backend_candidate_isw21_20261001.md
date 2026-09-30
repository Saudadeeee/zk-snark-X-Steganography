# ISW21 lattice zkSNARK candidate check (2026-10-01)

## Decision

ISW21 is the first candidate in this repository that passed a real upstream
Linux build and a prover/verifier smoke test on the current computer. Keep it
as a **research candidate**, not an accepted application backend. The proof
was for the upstream generic R1CS demo; it did not encode the video payload
opening relation, session policy, or normalized H.264 statement.

The upstream project explicitly describes itself as a proof-of-concept and
not production-ready. The construction is a *designated-verifier* lattice
zkSNARK: setup creates a verifier secret key. Any future integration must
therefore provision the verification key only to the designated verifier and
must not describe its proofs as publicly verifiable.

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

## First in-video size feasibility estimate

For upstream parameter class `B19C20`, the source fixes `n=2045`,
`query_num=8`, `query_size=4`, `pt_dim=32`, `tau=4`, and the message modulus
`p=2^19-1`. Its proof object contains an `a_vec` of 2,045 quadratic-extension
ring values and a `c_vec` of 36 such values. Each value has two coefficients
in the message field. If a future canonical serializer packs each coefficient
in exactly 19 bits after verifying it is in `[0,p)`, the arithmetic payload
would be:

```text
(2045 + 36) * 2 * 19 = 79,078 bits = 9,885 bytes after byte rounding
```

This is a **derived lower-bound estimate**, not an observed wire size: the
upstream proof type has no application-envelope serializer, and canonical
packing, parameter IDs, commitment fields, and framing still need to be
implemented and tested. The estimate is close enough to the measured 10,779
byte carrier budget reported for one 3,000-frame Coastguard stream that an
actual serialized proof/statement capacity test is mandatory before selecting
this backend. It does not prove all videos have enough capacity.

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

The commitment dimensions/distributions and their SIS hiding/binding estimates
are not selected. The relation, circuit, context encoding, and public-input
binding have not been implemented or reviewed. A passing generic R1CS demo
proves none of those properties.

## Remaining gates

- independently check the ISW21 security theorem and concrete parameter
  estimates for this exact circuit and designated-verifier setup;
- implement and review the bounded payload-opening relation and setup/key
  lifecycle, including verifier-key confidentiality;
- implement a canonical compact proof serializer/deserializer and reject
  non-canonical field encodings;
- produce a real proof for the application relation, measure its exact bytes,
  and embed/extract it blindly from H.264 Baseline/CAVLC with no proof sidecar;
- run wrong-payload, changed-context, malformed-proof, tamper, replay, expiry,
  and cross-session negative tests through the actual verifier; and
- benchmark repeated setup/prove/verify time, peak RSS, visual quality, and
  carrier capacity on multiple real videos and durations.

## Source references

- [ISW21 paper: *Shorter and Faster Post-Quantum Designated-Verifier
  zkSNARKs from Lattices*](https://eprint.iacr.org/2021/977)
- [Upstream reference implementation and build instructions](https://github.com/lattice-based-zkSNARKs/lattice-zksnark)
- [Pinned upstream source revision](https://github.com/lattice-based-zkSNARKs/lattice-zksnark/tree/48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e)
- [LaZer upstream requirements](https://github.com/lazer-crypto/lazer): Linux
  x86-64 with AVX-512 and AES. The local i7-12700H's Intel product
  specification lists AVX2, not AVX-512, so LaZer is not a local runtime
  candidate without different hardware.
