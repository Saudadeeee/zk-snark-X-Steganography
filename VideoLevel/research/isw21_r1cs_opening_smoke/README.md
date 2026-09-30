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
production parameter estimate, wire serializer, video proof envelope, or
H.264 integration. A passing result does not satisfy the target relation.

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
`CHANGED_COMMITMENT_PROOF=REJECTED`. Results must be reported together with
the explicit toy-parameter warning printed by the program.

## One measured smoke run

Measured 2026-10-01 in Ubuntu 24.04 x86-64 Docker on the Intel Core i7-12700H
host, GCC 13.3, Release build, pinned upstream revision above. One run produced:

| Measurement | Result |
| --- | ---: |
| R1CS constraints | 354 |
| QAP degree | 512 |
| Public inputs | 33 |
| LWE secret-key setup | 4.7776 s |
| CRS and verification-key setup | 0.4866 s |
| Prove | 0.0541 s |
| Verify (one accepted proof) | 0.0005 s |
| Process wall time, including negative checks | 5.53 s |
| Peak RSS | 410,156 KiB |

These are single-run smoke observations, not stable benchmark statistics.
Setup is dominated by the upstream designated-verifier key generation. The
proof was not serialized, so no proof byte count is claimed. Upstream's
`Linear comb size 835` is an internal element count, not bytes. This tiny,
insecure circuit says nothing about setup/prove performance, proof capacity,
visual quality, realtime behavior, or peak memory for the video relation.
