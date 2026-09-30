# ISW21 application-shaped R1CS smoke test

This isolated experiment exercises a small, explicit opening relation through
the upstream ISW21 lattice zkSNARK implementation. It is not the production
relation in `docs/LATTICE_VIDEO_ZKP_RELATION_v0.1.md` and does not select a
secure commitment suite.

## Relation in this smoke test

Public input is a 32-byte context digest and one field commitment. The private
witness is one byte of payload and a 16-bit binary opening. With
`q = 2^19 - 1`, deterministic public coefficients define:

```text
C = 31337 * payload
  + sum_i A_i * opening_bit_i
  + sum_j H_j * context_byte_j  (mod q)
```

The R1CS constrains context and payload bytes, each opening bit, the canonical
19-bit commitment representation, and the commitment equation. The complete
context bytes and original commitment are public SNARK inputs. Negative
checks require an altered payload witness, changed context, and changed
commitment to be rejected. A recentered pair changes one context byte and
adjusts the commitment by the corresponding public coefficient; although the
same witness still satisfies that new equation, the old proof must fail for
the changed full primary input.

## Security boundary

`q` is only 19 bits and the opening has only 16 bits. The coefficients are
deterministic test values. This is deliberately insecure and exists only to
test circuit wiring, primary-input binding, and invocation of the lattice SNARK
on an application-shaped relation. It provides no meaningful SIS security,
production parameter estimate, full proof envelope, or H.264 integration. A
passing result does not satisfy the target relation.

## Response coefficient size diagnostic

The real smoke proof contains 2,045 `a_vec` and 36 `c_vec` elements. Each is
a quadratic extension with two ring coefficients, for 4,162 response
coefficients total. For the pinned `B19C20` profile, the ring modulus is
`q = 2^108`; `p = 2^19 - 1` is the message/field modulus, not the ring
coefficient range. The source-level `rescale()` bound gives a conservative
exclusive coefficient bound of `rescale_q + p + 1 = 1,684,330,715,837`, below
`2^41`. The smoke test implements a parameter-specific canonical codec: encode
`a_vec` then `c_vec`, each extension's `c0` then `c1`, with 41 LSB-first bits
per coefficient. The final six unused high bits must be zero. This produces
an actual response encoding of 170,642 bits / 21,331 bytes.

The smoke binary measures coefficient count and maximum observed bit width
from the generated proof, checks every coefficient against that derived bound,
and verifies the proof again after decode. Tests reject modified response
bytes, wrong length, nonzero padding, and out-of-range coefficients. This is
an actual encoding of the upstream response object, but not a complete proof
envelope: it has no magic/version/parameter ID, public statement, session
metadata, framing, or H.264 integration. The response alone is about 1.98x the
10,779-byte payload transported in one 3,000-frame Coastguard experiment, and
2.23x the 9,568-byte raw-safe blind-stable capacity measured on a separate
300-frame Coastguard QP22/GOP1 input. The video conditions and capacity
definitions differ, so these comparisons identify a serious capacity risk,
not universal infeasibility.

For the actual native direct-CAVLC path, a separate 300-frame Akiyo CIF
capacity run committed 10,420 bits and rejected a 33,803-byte request. This
response encoding alone needs 170,648 physical bits—about 16.4x the committed
bits in that run, before the 14-byte carrier framing. It is not an embedding
test of this ISW21 response, and the ratio cannot be generalized to other
content or settings; it does show that the measured 300-frame IDR-only profile
cannot carry a response of this size. Details are in
[`isw21_response_native_capacity_probe_20261001.md`](../../benchmark/results/isw21_response_native_capacity_probe_20261001.md);
the earlier 33,803-byte comparison is in
[`native_payload_capacity_probe_20260930.md`](../../benchmark/results/native_payload_capacity_probe_20260930.md).

The upstream checkout must be pinned at
`48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e`; its libsnark submodule must match
the revision recorded there. Build in Linux x86-64 because this upstream
implementation is not supported as a native Windows build.

On Ubuntu 24.04, install the required build dependencies first:

```sh
sudo apt-get update
sudo apt-get install -y build-essential cmake git pkg-config libgmp-dev libssl-dev libboost-all-dev
```

```sh
git clone --recurse-submodules https://github.com/lattice-based-zkSNARKs/lattice-zksnark.git /tmp/lattice-zksnark
git -C /tmp/lattice-zksnark checkout --detach 48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e
git -C /tmp/lattice-zksnark submodule update --init --recursive
cmake -S research/isw21_r1cs_opening_smoke -B /tmp/isw21-opening-build \
  -DISW21_SOURCE_DIR=/tmp/lattice-zksnark -DWITH_PROCPS=OFF
cmake --build /tmp/isw21-opening-build --target isw21_r1cs_opening_smoke -j2
/tmp/isw21-opening-build/isw21_r1cs_opening_smoke
```

Expected terminal markers include `HONEST_R1CS=PASS`,
`ALTERED_PAYLOAD_WITNESS=REJECTED`, `NONCANONICAL_COMMITMENT=REJECTED`,
`LATTICE_SNARK_HONEST_VERIFY=PASS`, `CHANGED_CONTEXT_PROOF=REJECTED`,
`RECENTERED_CONTEXT_STATEMENT_PROOF=REJECTED`, and
`CHANGED_COMMITMENT_PROOF=REJECTED`, `PROOF_RESPONSE_ROUNDTRIP=PASS`,
`TAMPERED_SERIALIZED_RESPONSE=REJECTED`,
`MALFORMED_RESPONSE_ENCODINGS=REJECTED`, and
`SERIALIZED_RESPONSE_BYTES=21331`. Results must be reported together with the
explicit toy-parameter warning printed by the program.

## One measured smoke run

Measured 2026-10-01 in Ubuntu 24.04 x86-64 Docker on the Intel Core i7-12700H
host, GCC 13.3, Release build, pinned upstream revision above. One run produced:

| Measurement | Result |
| --- | ---: |
| R1CS constraints | 354 |
| QAP degree | 512 |
| Public inputs | 33 |
| LWE secret-key setup | 4.8416 s |
| CRS and verification-key setup | 0.4968 s |
| Prove | 0.0546 s |
| Verify (one accepted proof) | 0.0007 s |
| Verify after response decode | 0.0011 s |
| Process wall time, including negative checks | 5.59 s |
| Peak RSS | 410,336 KiB |
| Canonically encoded response bytes | 21,331 bytes |

These are single-run smoke observations, not stable benchmark statistics.
Setup is dominated by the upstream designated-verifier key generation.
Upstream's `Linear comb size 835` is an internal element count, not bytes.
The response encoding does not include the statement or an application/video
envelope. This tiny, insecure circuit says nothing about setup/prove
performance, complete proof capacity, visual quality, realtime behavior, or
peak memory for the video relation.
