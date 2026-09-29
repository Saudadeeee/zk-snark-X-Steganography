# Ringo/Buckler payload-opening relation probe

Research-only Go module pinned to `github.com/sp301415/ringo-snark@v0.0.0-20260924001507-306742714785`. It is **not** the application's ZKP backend and does not produce a video artifact.

The circuit uses a rank-8192 ring. A private 32-byte payload occupies 256 Boolean coefficient slots; all remaining slots are constrained to zero. Three private ternary polynomials are opening randomness. Two public full-ring equations have the shape `C_i = sum_j A_ij*r_j + B_i*m`, with NTT consistency constraints between coefficient and evaluation representations. For this probe, `A` and `B` are deterministically expanded from a fixed domain/seed and the canonical test statement. The custom commitment has no reviewed hiding/binding proof or concrete parameter analysis.

The application-level `verifyOpening` function receives only a context, public commitment and proof. It derives `A`, `B` and the exact 32-byte tail mask itself before invoking Buckler's low-level `Verify`. The test demonstrates that a proof under a prover-chosen all-zero mask passes the low-level verifier but is rejected by `verifyOpening`; do not bypass this verifier boundary. The compiled rank, field and CRS must also be pinned and independently reproduced in a real integration.

Run from this folder:

```powershell
go mod verify
go build ./...
go vet ./...
go test -count=1 -v ./...
```

The test accepts one valid witness and rejects changed commitment, changed context with the same commitment, non-Boolean payload, nonzero payload tail, and out-of-bound randomness. Its timing log is one local run, not a production benchmark. `prover.JindoParams.Size()/8` is a **550,249-byte estimate of Jindo commitments plus proof**, not serialized Buckler proof bytes. `proof_codec.go` provides a strict JSON codec and a schema-pinned binary codec for this experiment; neither is an adopted production format. No H.264 embedding, blind extraction, video quality or real session-policy test is performed here.

The complete-proof serialization rechecks on 2026-09-30 produced JSON proofs
from **2,710,137 to 2,710,642 bytes** and one schema-pinned binary proof of
**1,653,727 bytes**. These compare with the 550,249-byte estimate. Gzip at best
compression reduced one JSON sample to **1,281,918 bytes**. Neither binary nor
gzip fits the earlier measured carrier budget. A decoded proof verified;
the test rejected non-canonical/trailing
encodings, an empty proof structure, malformed proof shapes, changed context,
changed public commitment, non-Boolean payload, nonzero tail and randomness
outside the configured bound. The measured artifacts are far beyond the
10,779-byte carrier budget reported for the earlier Coastguard transport, so
these encodings do not fit that measured clip. This is a format-specific result,
not a proof that every video lacks sufficient capacity. The retained raw
capacity scan for the same 3,000-frame Coastguard asset measured 541,570 bytes
before patchability/quality losses. Proof-only figures do not include the
verifier's public commitment and statement. The full run details are in
[`ringo_opening_proof_wire_recheck_20260930.md`](../results/ringo_opening_proof_wire_recheck_20260930.md).

A follow-up field profile attributed 639,289 bytes to the 13 Buckler witness
commitments and 1,014,194 bytes to the Jindo evaluation proof; its `Encode`
vector alone was 557,295 bytes. BestCompression on binary measured 1,246,440
bytes, still 2.30x the raw-capacity upper bound of the same clip. These are
single-run diagnostics, not a repeated benchmark or an embedding attempt.
The circuit's inner/outer CRT moduli are 42/38 bits while this experimental
codec stores residues as 64-bit words. Even a highly optimistic all-proof
42/64 bit-packing estimate remains about 1.09 MB, around twice that clip's raw
capacity before framing or quality losses; bit packing alone cannot make this
particular cover fit.

`TestOpeningRankSizeSweep` additionally proves, serializes, decodes and
verifies the same opening circuit at ranks 256 through 4,096. Rank 256 is the
minimum that holds this exact 32-byte payload; it produced a **998,087-byte**
binary proof (**706,510 bytes** gzipped), still 1.84x/1.30x the measured
raw-capacity bound. Proof size falls only modestly with rank, while this probe
has no security analysis establishing that lower ranks are acceptable. The
measurements and limits are in the wire-format recheck report.

The relation also takes a canonical 282-byte `RGOS` v1 public statement
instead of an arbitrary context string. It includes fixed-width relation and
parameter IDs, registry root/epoch, session challenge, codec/carrier policy,
payload length/carrier count, carrier-position digest and normalized-video
commitment. Tests verify a proof under that context, then reject it when the
session, video digest, positions, codec policy, registry epoch or carrier
count changes. These values are fixtures, not values independently derived
from a real received video or trusted registry; replay-state and
challenge-expiry services are not implemented.

The in-band `RZV1` envelope now includes that 282-byte statement, the complete
canonical public commitment, and the binary proof, with zero padding to the
verifier-pinned carrier profile. At rank 8,192, the public commitment is
262,152 bytes and the minimum complete envelope is 1,916,177 bytes. The test
round-trips a fixed 2,000,000-byte envelope and verifies the decoded proof;
truncation, bad magic, forged field lengths, nonzero padding, changed session,
and changed public commitment are rejected. This is a transport-codec probe,
not actual H.264 embedding. Against the same cover's 541,570-byte raw-capacity
upper bound, even the 2,000,000-byte fixed profile is 3.69x too large.

On this Windows/amd64 host, plain `go test -race` aborts at an upstream CRT assembly `checkptr` alignment check. `go test -race -gcflags=all=-d=checkptr=0 -count=1 ./...` passed with the complete current test, but disabling `checkptr` does **not** resolve or exonerate the dependency issue. See [the recorded assessment](../results/ringo_opening_probe_20260929.md).
