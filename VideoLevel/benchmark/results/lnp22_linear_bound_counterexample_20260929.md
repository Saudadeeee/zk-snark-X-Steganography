# Pinned Go LNP22 exact witness-bound counterexample (2026-09-29)

## Reproduction

Module: `benchmark/lnp22_context_probe`, pinned dependency
`github.com/KarpelesLab/lnp22 v0.1.1` in `go.mod`/`go.sum`.

```powershell
cd benchmark/lnp22_context_probe
go test -run '^TestPinnedLNP22(LinearVerifierAcceptsProofForFalseBetaOneStatement|PayloadOpeningVerifierAcceptsNonBitWitnessTranscript)$' -count=1 -v .
```

Observed output on the Windows host:

```text
=== RUN   TestPinnedLNP22LinearVerifierAcceptsProofForFalseBetaOneStatement
--- PASS: TestPinnedLNP22LinearVerifierAcceptsProofForFalseBetaOneStatement (0.01s)
=== RUN   TestPinnedLNP22PayloadOpeningVerifierAcceptsNonBitWitnessTranscript
--- PASS: TestPinnedLNP22PayloadOpeningVerifierAcceptsNonBitWitnessTranscript (0.01s)
PASS
ok  github.com/zkstego/lnp22-context-probe  1.074s
```

Also ran `go test -count=1 ./...` (pass, 5.285 s package test time),
`go test -race -count=1 ./...` (pass, 11.654 s package test time), and
`go vet ./...` (exit 0) from the same Go module after adding the tests.
The unrelated public-Python fail-closed contract was checked with
`py -3.12 src/runtest/test_lattice_zkp.py`: **9/9 passed**. This is a scope
guard only; it does not repair the Go dependency or prove end-to-end video ZK.

The test source is
`benchmark/lnp22_context_probe/lnp22_dependency_assessment_test.go`. It uses
the same `HashToChallenge`, Gaussian masking and response equation as the
module's honest linear prover, but intentionally bypasses its witness-bound
precheck. The full proof is passed through this repository's canonical
LNPF-v2 serializer and decoder before the pinned `nizk.VerifyLinear` call.

## What is demonstrated

1. The first public equation is `1*s[0] = 2 (mod q)` with `q=8380417`, all
   other public rows zero, and `Beta=1`. No witness whose centered
   coefficients lie in `[-1,1]` can satisfy its constant coefficient. The
   normal `ProveLinear` returns an error for `s[0]=2`, but the canonical proof
   constructed from that witness is accepted by `VerifyLinear`. This is a
   false-statement counterexample for the **exact `Beta=1` relation** claimed
   by the pinned API, not a computational attack against the original LNP22
   paper under its own assumptions.
2. The second case uses the actual experimental 32-byte payload-opening
   matrix, setting one `bit=2` and its complement to `-1`. The standard
   prover rejects the out-of-bound witness; the canonical transcript is
   accepted by the verifier. This does not prove that the particular public
   commitment lacks *every* alternative in-bound opening, but it shows why
   prover validation and the `bit+complement=1` row are insufficient to claim
   proof of valid bytes.

The verifier directly checks the response bound `||z||_infinity <= BoundZ`
and the Fiat-Shamir linear equation; it does not verify an exact witness
`Beta` bound. A response bound is not a substitute for a sound boundedness
argument. Existing `VerifyRange` and two-ring verifier defect tests in the
same file prevent treating those paths as an automatic repair.

## Decision

Do not integrate this Go linear proof as the application's payload-opening
ZKP. The real 8,203-byte serialized probe proof is useful for relation and
transport sizing research only; it does **not** prove the required 32-byte
payload encoding. A reviewed proof system for the exact bounded relation (or
a reviewed fix with independent security analysis) is required before any
in-video result could meet the system goal.
