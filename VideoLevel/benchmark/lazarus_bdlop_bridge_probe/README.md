# LaBRADOR / BDLOP-shaped opening bridge probe

This is a research-only integration probe, not the product backend and not a
security validation of BDLOP. It maps the BDLOP opening equations onto the
LaBRADOR sparse relation API using a deterministic uniform matrix seed. The
opening uses LaBRADOR's Gaussian sampler (`sigma=49.6`), not the Go dependency's
default sampler (`sigma=50`). The relation constrains exactly four fixed-width
byte slots using boolean bits, reconstruction equations, and constant-term
pinning; it is not an arbitrary-length payload encoding.

The pinned upstream checkout is Lazarus commit
`4363e5151a25dac2e96885cd08c1bdfb7ac3c1af`. The test was run with Docker image
`rustlang/rust:nightly-slim-2026-09-15`, digest
`sha256:66726eb549e867024ed4b890cb133e7304b52cc2f380d425b7ce210849970894`.

From this directory, run `./run_probe.ps1`. It creates a fresh clone under
`$env:TEMP`, checks out the pinned revision, copies the checked-in Rust test
into `labrador/tests`, and runs only that integration test in Docker. The
temporary clone is deliberately retained so its source and build artifacts
remain inspectable.

The observed fixture had opening norm-squared `1,601,036` under fixed bound
`5,000,000`; prove and verify passed, and context/target mutations rejected.
The four-byte encoding adds 2,311 relation constraints, and the measured test
runtime was 179.12 s in the latest clean run (21.71 s initial build). This is
a candidate feasibility datum, not a distributional benchmark; it is far from
realtime.
This establishes only that this fixed system can express and prove the selected
linear opening equations plus a 4-byte range/encoding relation. The underlying
LaBRADOR paper explicitly disregards zero knowledge for its base protocol and
only suggests a separate witness-masking shim; this probe does not implement
that shim. Consequently it is **not a ZKP** and its proof must be treated as
potentially witness-revealing. It also does not establish hiding/binding,
secure parameters, arbitrary payload encoding, canonical full statement
hashing, proof serialization, or H.264 capacity. In particular,
`statement_hash` is specific to this hard-coded probe builder and omits the
explicit matrix and constraint schema. Do not enable this backend in the video
pipeline based on this result.
