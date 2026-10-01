# ISW21 application-shaped R1CS smoke test

This isolated experiment exercises a small, explicit opening relation through
the upstream ISW21 lattice zkSNARK implementation. It is not the production
relation in `docs/LATTICE_VIDEO_ZKP_RELATION_v0.1.md` and does not select a
secure commitment suite.

## Relation in this smoke test

Public input is a 32-byte context digest and a 128-coordinate commitment
vector. The private witness is a 32-byte payload and a 2,816-bit opening. With
`q = 2^19 - 1`, AES-PRG-generated public matrices define a KTX-shaped toy
linear commitment over the little-endian bits of payload, context, and opening:

```text
C = A * (payload_bits || context_bits) + B * opening_bits  (mod q)
```

The R1CS constrains context and payload bytes, all 2,816 opening bits, and each
of the 128 commitment equations. The complete context bytes and commitment
vector are public SNARK inputs (160 public inputs total). Negative checks
require an altered payload witness, altered opening, changed context, and
changed commitment to be rejected. A recentered pair changes one context byte
and adjusts the commitment by the corresponding public matrix column; although
the same witness still satisfies that new equation, the old proof must fail
for the changed full primary input.

## Security boundary

`q` is only 19 bits, the dimensions are not selected from a concrete SIS
estimate, and the PRG-generated key is only a smoke fixture. This exists only
to test circuit wiring, primary-input binding, and invocation of the lattice
SNARK on a full-length payload/opening relation. It provides no established
SIS security, production parameter estimate, full proof envelope, or H.264
integration. A passing result does not satisfy the target relation.

**Experimental separate-process verifier path:**
`--export-verifier-key FILE --export-extracted-proof FILE` writes a
parameter-tagged, fixed-width little-endian verifier key and an envelope with
the public primary input plus the canonical proof response. A second process
can run `--verify-extracted-proof FILE --verifier-key FILE
--expected-context-hex 64_HEX_DIGITS`. The expected context is supplied by
the verifier's own session state; the verifier compares it with the public
context in the proof before checking the lattice proof. The prover may set the
32-byte public context with `--prover-context-hex 64_HEX_DIGITS`; omitting it
uses the fixed fixture shown below. The verifier rejects a missing context
and replay into a different expected context. A replay within the same
expected context can still pass: there is no consumed-session registry,
canonical session/video digest, or expiry policy. The verifier key
contains the LWE secret key; the writer sets its file mode to `0600` on POSIX,
but this unencrypted file must remain private to the designated verifier. The
format stores the exact 128-bit ring-component representation used by this
upstream arithmetic, rather than relying on libff's generic serializer. It
checks magic/version, fixed dimensions, field ranges, exact response size,
trailing bytes, and file truncation. The verifier still does not need the
prover CRS or KTX matrices. CTest now runs the producer and verifier as
separate processes and checks honest acceptance, changed context, modified
response, truncation, wrong expected session context in both directions,
missing expected context, a separately generated second-context proof, and
wrong setup key rejection, and verifier-key file permissions. This establishes
only a smoke-level file/process boundary: the codec has not been audited for
production use, setup/key authenticity and confidentiality must be
provisioned out of band, and the proof is not bound to an H.264 context.

The first attempt to export the key exposed an upstream QAP-prefix bug:
`gen_q_mat()` called `reserve()` and copied through `begin()` without resizing
the three prefix vectors, so the verifier read outside their logical vector
sizes. The reproducible smoke therefore also applies the tracked
[`upstream_qap_prefix_resize_fix.patch`](upstream_qap_prefix_resize_fix.patch)
to resize A/B/C prefixes before copying. This is an additional local research
patch, not a fix merged upstream.

**Cryptographic run caveat:** source review found that the pinned upstream
revision closes a function-static `/dev/urandom` stream after its first read
and reuses that closed stream in later seed-generation calls. Later calls can
therefore expand uninitialized seed bytes. The reproducible procedure below
applies [`upstream_rng_fix.patch`](upstream_rng_fix.patch) to the temporary
checkout: each seed read now opens a fresh stream and throws on open/read
failure. The upstream repository itself remains unchanged. The measured run
below was rerun after applying this patch, but remains only a smoke run and
has not had an independent cryptographic implementation audit.

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
patch --no-backup-if-mismatch -d /tmp/lattice-zksnark -p1 < research/isw21_r1cs_opening_smoke/upstream_rng_fix.patch
patch --no-backup-if-mismatch -d /tmp/lattice-zksnark -p1 < research/isw21_r1cs_opening_smoke/upstream_qap_prefix_resize_fix.patch
cmake -S research/isw21_r1cs_opening_smoke -B /tmp/isw21-opening-build \
  -DISW21_SOURCE_DIR=/tmp/lattice-zksnark -DWITH_PROCPS=OFF
cmake --build /tmp/isw21-opening-build --target isw21_r1cs_opening_smoke -j2
ctest --test-dir /tmp/isw21-opening-build --output-on-failure
/tmp/isw21-opening-build/isw21_r1cs_opening_smoke
```

The CTest integration writes a verifier-only key file and an
extracted-proof-envelope fixture to a temporary directory, then starts a
second process to verify it. For manual inspection, export and verify using
separate commands (the key file is secret and must not be distributed):

```sh
/tmp/isw21-opening-build/isw21_r1cs_opening_smoke \
  --export-verifier-key /tmp/isw21-verifier.key \
  --export-extracted-proof /tmp/isw21-extracted-proof.bin
/tmp/isw21-opening-build/isw21_r1cs_opening_smoke \
  --verify-extracted-proof /tmp/isw21-extracted-proof.bin \
  --verifier-key /tmp/isw21-verifier.key \
  --expected-context-hex 913ae120775802b46ca91108d2334f8029f163059a4418ce7d26b0520f8bd731
```

The `.bin` file is an experimental extracted statement/response envelope, not
a video and not a production sidecar protocol. The measured smoke envelope is
23,907 bytes (160 public field elements plus the 21,331-byte response and
framing); the designated verifier key is 2,419,872 bytes and stays outside the
video.

A separate native video probe carried that entire 23,907-byte envelope, plus
the 14-byte `ZKVP` transport header, in a real 704x576 H.264 clip. Blind
extraction recovered the exact proof bytes from video alone, and an independent
verifier process accepted them with the expected context and rejected a wrong
expected context. The measured blind extraction took 1,819.342 seconds for
a 45.846-second clip, so this path is not realtime. See
[`isw21_full_envelope_video_only_probe_20261001.md`](../../benchmark/results/isw21_full_envelope_video_only_probe_20261001.md)
for input hashes, NAL counts, visual quality, CPU/RAM limits, and the remaining
security gaps. This does not make the toy relation the target application
relation: its context is still a fixture rather than a verifier-pinned
session/video digest.

Expected terminal markers include `HONEST_R1CS=PASS`,
`ALTERED_PAYLOAD_WITNESS=REJECTED`, `COMMITMENT_EQUATION_MISMATCH=REJECTED`,
`LATTICE_SNARK_HONEST_VERIFY=PASS`, `CHANGED_CONTEXT_PROOF=REJECTED`,
`RECENTERED_CONTEXT_STATEMENT_PROOF=REJECTED`, and
`CHANGED_COMMITMENT_PROOF=REJECTED`, `PROOF_RESPONSE_ROUNDTRIP=PASS`,
`TAMPERED_SERIALIZED_RESPONSE=REJECTED`,
`MALFORMED_RESPONSE_ENCODINGS=REJECTED`, and
`SERIALIZED_RESPONSE_BYTES=21331`, `PAYLOAD_BYTES=32`,
`OPENING_BITS=2816`, `KTX_COMMITMENT_ROWS=128`, and
`ALTERED_OPENING=REJECTED`. Results must be reported
together with the explicit toy-parameter warning printed by the program.

## One measured smoke run

Measured 2026-10-01 in Ubuntu 24.04 x86-64 Docker on the Intel Core i7-12700H
host, GCC 13.3, Release build, pinned upstream revision above. One run produced:

| Measurement | Result |
| --- | ---: |
| R1CS constraints | 3,520 |
| QAP degree | 4,096 |
| Public inputs | 160 |
| LWE secret-key setup | 5.1720 s |
| CRS and verification-key setup | 3.8536 s |
| Prove | 0.3281 s |
| Verify (one accepted proof) | 0.0006 s |
| Process wall time, including negative checks | 9.82 s |
| Peak RSS | 481,052 KiB |
| Canonically encoded response bytes | 21,331 bytes |

The table records the first observed post-patch run, not a stable benchmark
statistic. A second fresh process also exited 0 with the same honest-proof
and negative-case markers; its wall time was 9.12 s and peak RSS 481,076 KiB.
The first smoke process reported `HONEST_R1CS=PASS`,
`LATTICE_SNARK_HONEST_VERIFY=PASS`, and rejected altered payload, opening,
context, commitment, and proof-response encodings. The upstream source
reported `QAP degree: 4096`. Upstream's
`Linear comb size 7460` is an internal element count, not bytes. The response
encoding does not include the statement or an application/video envelope.
The patch fixes only the observed seed-stream lifetime bug; it is not an
independent security audit of the upstream cryptography. The tiny-modulus
relation says nothing about production security, complete proof capacity,
visual quality, realtime behavior, or peak memory for the video relation.
