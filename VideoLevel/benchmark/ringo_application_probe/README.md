# Ringo/Buckler payload-opening relation probe

Research-only Go module pinned to `github.com/sp301415/ringo-snark@v0.0.0-20260924001507-306742714785`. It is **not** the application's ZKP backend and does not produce a video artifact.

The circuit uses a rank-8192 ring. A private 32-byte payload occupies 256 Boolean coefficient slots; all remaining slots are constrained to zero. Three private ternary polynomials are opening randomness. Two public full-ring equations have the shape `C_i = sum_j A_ij*r_j + B_i*m`, with NTT consistency constraints between coefficient and evaluation representations. For this probe, `A` and `B` are deterministically expanded from a fixed domain/seed and supplied context. The context is an arbitrary test string, **not** the project's canonical video/session statement. The custom commitment has no reviewed hiding/binding proof or concrete parameter analysis.

The application-level `verifyOpening` function receives only a context, public commitment and proof. It derives `A`, `B` and the exact 32-byte tail mask itself before invoking Buckler's low-level `Verify`. The test demonstrates that a proof under a prover-chosen all-zero mask passes the low-level verifier but is rejected by `verifyOpening`; do not bypass this verifier boundary. The compiled rank, field and CRS must also be pinned and independently reproduced in a real integration.

Run from this folder:

```powershell
go mod verify
go build ./...
go vet ./...
go test -count=1 -v ./...
```

The test accepts one valid witness and rejects changed commitment, changed context with the same commitment, non-Boolean payload, nonzero payload tail, and out-of-bound randomness. Its timing log is one local run, not a production benchmark. `prover.JindoParams.Size()/8` is a **550,249-byte estimate of Jindo commitments plus proof**, not measured serialized Buckler proof bytes. This pinned Buckler revision has no complete canonical proof encoder/decoder. No H.264 embedding, blind extraction, video quality or real session-policy test is performed here.

On this Windows/amd64 host, plain `go test -race` aborts at an upstream CRT assembly `checkptr` alignment check. `go test -race -gcflags=all=-d=checkptr=0 -count=1 ./...` passed with the complete current test, but disabling `checkptr` does **not** resolve or exonerate the dependency issue. See [the recorded assessment](../results/ringo_opening_probe_20260929.md).
