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

The commitment dimensions/distributions and their SIS hiding/binding estimates
are not selected. The relation, circuit, context encoding, and public-input
binding have not been implemented or reviewed. A passing generic R1CS demo
proves none of those properties.

## Remaining gates

- independently check the ISW21 security theorem and concrete parameter
  estimates for this exact circuit and designated-verifier setup, including
  the quantum attack against its knowledge-based LWE linear-only assumption,
  the stronger LTM route to knowledge soundness, the 40-bit statistical ZK
  parameter, and the non-reusable verification-oracle model;
- implement and review the bounded payload-opening relation and setup/key
  lifecycle, including verifier-key confidentiality;
- extend the response-only codec into a versioned proof/statement envelope,
  including parameter identifiers, session fields, and canonical rejection;
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
- [LUNA, ePrint 2022/1690](https://eprint.iacr.org/2022/1690): later analysis of
  ISW21's knowledge-based LWE linear-only assumption, the weaker LTM route to
  argument soundness, and conditions required to recover knowledge soundness.
- [Debris-Alazard, Fallahpour, Stehlé, ePrint 2024/030](https://eprint.iacr.org/2024/030):
  quantum oblivious sampling attack on the standard-model lattice-SNARK
  knowledge assumption discussed by LUNA.
- [LaZer upstream requirements](https://github.com/lazer-crypto/lazer): Linux
  x86-64 with AVX-512 and AES. The local i7-12700H's Intel product
  specification lists AVX2, not AVX-512, so LaZer is not a local runtime
  candidate without different hardware.
