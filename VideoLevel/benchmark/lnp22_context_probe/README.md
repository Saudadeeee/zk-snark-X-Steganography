# LNP22 context-binding feasibility probe

This directory is an isolated experiment against `github.com/KarpelesLab/lnp22`
v0.1.1. It checks that a public linear statement can be augmented with rows
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
cmd /c "go run . -proof-out proof_$run.json -relation-out relation_$run.json < statement_$run.json"
```

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
