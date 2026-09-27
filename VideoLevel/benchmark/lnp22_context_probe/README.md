# LNP22 context-binding feasibility probe

This directory is an isolated experiment against `github.com/KarpelesLab/lnp22`
v0.1.1 at commit `878cf9d5bf73ae387b73a0843edc3364fd0f6be4`, with module
checksum `h1:7iSrrkrzYDxOF8Dx34OSzNZ6o6GD0URS5DrTE5BjA3w=` pinned in `go.sum` and
checked against Go build metadata. It checks that a public linear statement can be augmented with rows
derived from a bounded byte string and that the serialized proof verifies only
with the matching context. It is **not** the video application relation and is
not an implementation of the system's H.264 embedding/extraction pipeline.

The probe samples a fresh random base matrix and a short witness on each run,
then computes the matching target itself. Therefore it proves knowledge for
that generated relation; it does not prove video authenticity, codec behavior,
or any property of an externally supplied video. The relation JSON is an
experimental public artifact needed to check this probe and is not evidence
that the project's no-proof-sidecar requirement has been met. The library and
this construction have not received an independent cryptographic audit.

## Reproduce

From this directory, run tests and static checks:

```powershell
go test ./...
go test -race ./...
go vet ./...
go mod verify
```

To run a context-bound proof experiment, write the exact bytes to be bound to a
file and redirect that file to stdin (this avoids PowerShell transforming a
byte-array pipeline). Choose two output paths that do not already exist:

```powershell
$run = Get-Date -Format 'yyyyMMdd_HHmmss'
[System.IO.File]::WriteAllText(
  ".\statement_$run.json",
  '{"protocol":"probe-only","statement":"sample"}',
  [System.Text.UTF8Encoding]::new($false)
)
$proofRun = cmd /c "go run . -proof-out proof_$run.json -relation-out relation_$run.json < statement_$run.json" | ConvertFrom-Json
$proofRun | ConvertTo-Json -Compress
```

The CLI exposes verification with an expected base-relation hash:

```powershell
cmd /c "go run . -verify -proof-in proof_$run.json -relation-in relation_$run.json -trusted-base-relation-sha256 $($proofRun.base_relation_sha256) < statement_$run.json"
```

That example demonstrates the verifier interface only. In a real deployment,
the expected relation hash must come from independently trusted configuration
(for example, a verifier-pinned signed registry), not from the prover's report.
For a local round-trip smoke test, the generated hash can be fed back from
`$proofRun`; that is a self-consistency check, not an independent trust decision.
The verifier exits 0 only when `valid:true`; a structurally valid but rejected
proof emits `valid:false` and exits nonzero. Malformed input also exits nonzero.

Input is capped at 1 MiB. The command reports proof and relation sizes, elapsed
prove/verify time, a proof digest, a positive verification result, and whether
changing the bound context is rejected. Timings are a single local sample, not
a benchmark distribution. The random base relation and context-binding method
must not be represented as a production protocol or an audited ZKP adaptation.

## Current limitation

This probe does not yet parse and validate the application's fixed video
statement, prove a useful video property, serialize a verifier-ready application
protocol, embed proof bytes in H.264 residuals, or blind-extract a proof from a
video. It is feasibility evidence only; the end-to-end objective remains
incomplete.

## Recorded local sample

One run on 2026-09-27 using the project's 1,195-byte canonical statement
reported 12 context units, a 57,499-byte proof, and a 184,717-byte public
relation artifact. Proving took 51.026 ms and verification took 27.300 ms;
verification passed and changing the context was rejected. The proof SHA-256
was `27936e592d79595cb632466de90324689512627db95ed9ace2159ce57732548b`.
This is a single timing sample for the random base relation described above,
not a video ZKP benchmark or an estimate of end-to-end embedding performance.
The serialized augmented rows were also independently reconstructed with the
project's Python `derive_statement_context_units()` implementation: all 12
context limbs matched exactly for this statement. This checks cross-language
encoding consistency only; it does not validate the meaning of the relation.

After adding the verifier-pinned relation digest, another local run on
2026-09-27 produced a 57,415-byte proof; the generation report measured prove
at 50.091 ms and its in-process verification at 29.229 ms. A separate CLI
verifier invocation returned `valid=true`; its own duration was not captured.
The configured base-relation digest was
`d9952d5b5df6ac53f8e0fe1364ca29e16d46a5990e10f99863aa7756f97fccd1`. A
separate CLI run with one statement byte changed exited with code 1 and
reported a context-digest mismatch. Another run incremented one canonical
proof response coefficient; it printed `valid:false`, exited with code 1, and
reported proof rejection. These verify the probe CLI's pin/context/proof
checks; the generated base relation was still random and the pin was not
provisioned by an independent registry.

## Coastguard patchability scan

The 2026-09-27 run in
`benchmark/results/streaming_patchable_capacity_lnp22_context_coastguard_3000f_20260927.json`
processed 3,000 frames of `coastguard_cif_q22_g1_3000f.h264` in 2,126.292 s.
For the earlier 57,458-byte probe artifact (SHA-256
`e7e018d64ea2ddf837a3b6b9ada36c488f2d81733d320ffa92b5fc8d71cb8c3c`) plus
16 framing bytes, the patcher confirmed exactly 459,792 bit positions—an exact
fit with zero headroom. The video had 4,332,560 raw safe candidates. The scan
report explicitly leaves `quality_validated` and `blind_extraction_validated`
false, and it did not write an embedded video. It therefore establishes
patchability for this exact older artifact only, not successful embedding,
visual quality, or blind verification. It also cannot be generalized to the
newer 57,499-byte sample above.
