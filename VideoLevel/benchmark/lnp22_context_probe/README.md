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

### Pinned dependency range-proof gate (2026-09-28)

Do not use `github.com/KarpelesLab/lnp22` v0.1.1 `nizk.VerifyRange` as a
security check. A dynamic negative test generated a valid range proof, removed
all `BitProofs`, replaced `ReconProof` with all-zero vectors having the expected
shape, and observed `VerifyRange` return `true`. The test intentionally failed
because it expected rejection; the temporary test file was removed after this
one-off audit. The pinned verifier checks the linear proof, then only the
shape/norm of bit and reconstruction proof data instead of verifying those
subproof relations ([verifier at pinned revision](https://github.com/KarpelesLab/lnp22/blob/878cf9d5bf73ae387b73a0843edc3364fd0f6be4/nizk/verifier.go#L30-L53)).

This finding applies to the dependency's range-proof API; this probe's current
video proof uses `ProveLinear`/`VerifyLinear`, not `ProveRange`/`VerifyRange`.
It is not a full audit of the linear proof implementation. Do not claim payload
range constraints from this dependency unless a corrected, pinned implementation
passes negative tests that tamper with or omit every subproof.

The same pinned module's `tworing` package is also disqualified from verifier
use. `TestPinnedLNP22TwoRingVerifierAcceptsQuadraticForgeryFromUnhashedWy`
constructs an impossible statement (`B = 0`, `V = 1`) and a proof with `Z = 0`,
`Wq = 0`, and `Wy = -c²`. The test independently mirrors the pinned
Fiat-Shamir transcript, computes `c`, then sets `Wy`; it passes because
`tworing.hashToChallenge` omits `Wy` while `tworing.Verify` consumes it in the
quadratic equation. This is a runtime-reproduced soundness forgery, not merely
a source-level concern. The assessment test also confirms that `Statement.Norm`
is rejected by the honest prover for an out-of-bound witness, yet is not
checked by the verifier; the implementation computes a response norm then
discards it. Do not use this package for quadratic or norm-constrained
application proofs unless upstream fixes the transcript and verifier, and the
fixed revision receives independent cryptographic review.

`TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening` separately
characterizes the application-relation gap: with the same pre-provisioned
relation witness, the probe can generate accepted proofs under two distinct
`payload_commitment` context values. The proof binds the selected context, so a
proof for context A does not verify under context B; however, the underlying
fixed witness relation does not establish that either commitment opens to the
embedded payload. This is expected for this transport probe and must be fixed
in a future application relation, not by weakening the context-binding check.

This experimental path serializes a video-context statement, transports a
complete proof artifact through H.264 residuals, and implements blind
extraction. A real full-size transport E2E run is now recorded in
`benchmark/results/lnp22_video_e2e_compact_20260928T1109.json`: the 3,000-frame
352x288 Coastguard stream carried a 9,227-byte LNPF-v2 proof in a 10,446-byte
envelope across 9 of 30 segments. The emitted 98,479,704-byte H.264 stream
passed strict decode; the run report records video-only blind extraction and
`verification_result.valid: true`. Its measured pipeline time was 16,931.57 s
(about 4 h 42 min), 0.177 frames/s, with 3,664.95 MB peak process-tree RSS.
This is one development-host run, not a representative performance
distribution or realtime result; the report explicitly identifies the proof
as experimental and says it does not prove payload-commitment opening or
encoder correctness.

A distinct standalone `verify` recheck of that published output completed and
is recorded in
`benchmark/results/lnp22_video_e2e_compact_20260928T1109.verify.json`. It
reports `valid: true`, a 9,227-byte LNPF-v2 proof, 86,232 carriers, and 5.309 ms
for cryptographic verification after extraction. This confirms that this
video's extracted experimental proof verifies against its separately pinned
relation; it does not prove a useful product-registered application/video
property and has no independent cryptographic audit. Full video extraction
remains very slow, and the end-to-end objective is incomplete.

The package also contains an explicitly experimental fixed-relation CLI
(`-fixed-setup`, `-fixed-prove`, `-fixed-verify`) and helper tests. Setup creates
a random short linear relation once; verifier configuration must independently
pin its reported SHA-256 digest. Prove/verify consume the same canonical JSON
context, and the CLI emits/accepts the compact proof bytes. This proves only
knowledge for that provisioned secret relation: context augmentation does not
prove that a payload is present in a video, that a video satisfies a property,
or that the embedder followed the claimed codec policy. The CLI is not wired to
the production application API or registry. The experimental `video_e2e.py`
driver does call the fixed-relation CLI while creating/verifying the H.264
payload, and the experimental loopback `http_api.py` delegates its jobs to
that driver. This proves the probe components are connected; it does not turn
the random fixed relation into a registered product relation or make the API
production-ready.

Example from this directory (the statement file must be canonical UTF-8 JSON,
without a BOM or trailing newline):

```powershell
$setup = go run . -fixed-setup -relation-out relation.json -witness-out witness.json | ConvertFrom-Json
# Keep witness.json secret. Provision relation.json and its digest to verifiers
# through trusted configuration; never trust the digest reported by a prover.
cmd /c "go run . -fixed-prove -relation-in relation.json -witness-in witness.json -proof-out proof.lnpf < statement.json"
cmd /c "go run . -fixed-verify -relation-in relation.json -proof-in proof.lnpf -trusted-base-relation-sha256 $($setup.relation_sha256) < statement.json"
```

This standalone CLI smoke format does not mean `proof.lnpf` is embedded in
video. It remains a standalone proof CLI; the experimental video transport
driver described below is separate from the production API and registry.

### Compact context-bound proof experiment (LNPF v2)

The CLI also exposes `-fixed-compact-prove` and `-fixed-compact-verify`. This
format avoids adding 12 context limbs as extra witness polynomials: it hashes
the canonical context with SHA3-256 and applies a determinant-one polynomial
row operation to the pinned public linear statement before calling
`ProveLinear`/`VerifyLinear`. The operation is invertible, so it preserves the
same short-relation witness; a unit matrix entry is required to make distinct
context digests yield distinct transformed statements. The context-derived
statement changes the LNP22 Fiat-Shamir transcript without increasing proof
dimensions.

The resulting binary format is `LNPF` version 2 and, with the pinned default
parameters, is exactly 9,227 bytes (`11 + (4 + 5) * 256 * 4`), compared with
33,803 bytes for the v1 augmented-context format. The saved size is real for
the standalone generated proof, but has not yet been measured in the video
transport or evaluated for visual quality/capacity. These compact commands
are an experimental adaptation of the upstream protocol, have not received an
independent cryptographic review, and still prove only knowledge of the
provisioned short-relation witness—not a payload opening, a video property, or
encoder correctness. The video driver supports both representations:
`--proof-mode augmented` (default, `LNPF` v1) preserves the earlier path,
while `--proof-mode compact` selects the experimental v2 prover. The verifier
reads the extracted `LNPF` version byte and selects the matching verifier, so
video-only verification does not need a mode flag. This integration has
pipeline unit/mocked coverage and standalone real Go proof round-trip tests;
it has not yet completed a compact proof embedded in a real video. Therefore
the v2 size reduction is not evidence of actual video capacity, quality, or
runtime improvement.

```powershell
# Run the loopback issuer in a separate terminal using the verifier's pinned
# 32-byte policy digest and verifier-owned durable database.
py -3.12 -m src.zkp_session_http --database ./.state/sessions.sqlite3 `
  --context-binding-hex <64-hex-policy-digest>
# Request a fresh challenge from that verifier process. Do not give the SQLite
# database to the prover; pass only the returned public challenge to embed.
$sessionGrant = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/v1/zkp/sessions

py -3.12 benchmark/lnp22_context_probe/video_e2e.py embed `
  --video input.h264 --output compact-stego.h264 `
  --relation relation.json --witness witness.json `
  --trusted-relation-sha256 <pinned-relation-sha256> `
  --session-challenge-hex $sessionGrant.challenge `
  --report-output compact-report.json --proof-mode compact

# Run this on the verifier side with its session database and pinned binding.
# This blind extraction/proof check atomically consumes the challenge.
py -3.12 benchmark/lnp22_context_probe/video_e2e.py verify `
  --video compact-stego.h264 --relation relation.json `
  --trusted-relation-sha256 <pinned-relation-sha256> `
  --session-database ./.state/sessions.sqlite3 `
  --session-context-binding-hex <64-hex-policy-digest>
```

```powershell
cmd /c "go run . -fixed-compact-prove -relation-in relation.json -witness-in witness.json -proof-out proof-compact.lnpf < statement.json"
cmd /c "go run . -fixed-compact-verify -relation-in relation.json -proof-in proof-compact.lnpf -trusted-base-relation-sha256 $($setup.relation_sha256) < statement.json"
```

For size feasibility, this test-only helper serializes its proof in `LNPF` v1:
an 11-byte version/dimension header followed by canonical big-endian `uint32`
coefficients for `W` then `Z`. The verifier requires exact dimensions and byte
length and rejects coefficients `>= q`. With the current default parameters
and 12 context limbs, the encoded artifact is exactly 33,803 bytes
(`11 + (16 + 17) * 256 * 4`), versus 57,415 bytes for the earlier JSON probe
artifact. This is a 41.1% representation reduction, not a smaller cryptographic
proof or a measured video embedding result; the experimental driver below
implements the intended transport run, but actual proof embedding,
blind-extraction and visual-quality gates remain unrun for this proof.

## Experimental proof-in-video driver

`video_e2e.py` has an explicitly unregistered experiment that wraps the
canonical context, complete serialized `LNPF` proof, and a short public demo
payload, then passes those bytes to the existing blind CAVLC channel. Relation
setup is a separate operation: the `embed` command requires a pre-provisioned
public relation, its private witness, and a verifier-configured relation digest.
It rejects a relation whose embedded digest differs from that trust pin and
never generates or chooses a new relation during proving. It then proves the
context, selects carriers, embeds the full envelope into H.264, enforces the
strict decoder gate, extracts from the stego video, recomputes the carrier
positions and normalized video digest, and invokes the Go verifier with the
same independently supplied trust pin. The relation remains a public
configuration artifact and the witness stays outside the report. The proof
exists only inside the video's CAVLC residual carriers after the temporary
directory is removed. `verify` accepts the video, public relation config, a
verifier-pinned relation digest, and an out-of-band sync key; it does not load a
proof sidecar.

The pinned dependency's `nizk.DefaultParams()` currently sets the Dilithium
ring (`N=256`, `q=8,380,417`), `K=4`, `L=5`, `kappa=60`, `beta=1`,
`sigma=350`, and `BoundZ=1400`. These are the library defaults observed in
v0.1.1, **not** a documented security-level claim for this application. This
integration has no independent cryptographic audit or reviewed application
parameter selection; proof-size and round-trip tests do not establish
soundness, zero-knowledge, or post-quantum security at a stated level.

### Exact claim in the current compact probe (not the final application relation)

Let the verifier provision and pin the base relation `(A,t)` and let the
prover hold witness vector `s`. In the configured ring
`R_q = Z_q[X]/(X^N+1)`, the base relation is
`A*s = t (mod q)` with coefficient-wise infinity norm `||s||_inf <= beta`.
The setup routine samples `A` and a short `s`, then computes `t=A*s`; the
verifier must trust the relation digest through independent configuration.
The fixed relation and witness artifacts are setup inputs, not generated by
the video receiver or extracted from the video.

For canonical context bytes `C`, compact binding computes
`d = SHA3-256(domain || uint64_be(len(C)) || C)`, encodes `d+1` injectively as
the base-`q` coefficients of a polynomial `p(C)`, and chooses a row `j>0` with
a unit matrix entry. It constructs
`A_C[0,*] = A[0,*] + p(C) A[j,*]` and
`t_C[0] = t[0] + p(C) t[j]`, leaving the other rows unchanged. This
determinant-one row operation is invertible, so the short witness remains the
same and `A_C*s=t_C` is equivalent to `A*s=t`. The prover runs LNP22
`ProveLinear` on `(A_C,t_C,s)`; the verifier reconstructs the same statement
from `C` and the pinned base relation before calling `VerifyLinear`.

Thus, if the pinned relation and implementation are trusted, an accepted proof
shows knowledge of the short witness for that verifier-pinned relation, with
the LNP22 transcript bound to this exact canonical context. In the video
driver, `C` includes the session ID, payload commitment, carrier-normalized
video digest, carrier-position digest, codec/embedding policy, and protocol
version. The receiver separately recomputes the payload and video-derived
fields from the extracted envelope and the video. This is a context-bound
proof-of-possession/attestation claim only. It does **not** prove that the
video was captured by a particular device, that its H.264 encoder followed a
claimed process, or that any application-specific predicate over pixels was
true. The current random setup is not a product identity registry, and the
relation transform/library implementation has not received independent
cryptographic review; do not describe this probe as production-secure or as
the final application ZKP.

The envelope is protocol v3. Its statement names the recomputable
`canonical_video_sha256` instead of carrying an unverifiable raw `cover_hash`
or ambiguous `stego_hash`. The blind verifier rederives carrier positions and
recomputes the carrier-normalized H.264 digest; the statement pins the policy
as `canonical-h264-carrier-normalized-sha256-v1`. Protocol-v2 artifacts are
incompatible with the v3 statement parser; an already-running v2 process does
not adopt the v3 code on disk. The proof claim is
knowledge of the verifier-pinned short linear-relation witness bound to this
public context; it still does not prove payload commitment opening or encoder
correctness.

Set the sync key in a secret manager or a private shell environment. Do not
print it or put it on the command line:

```powershell
$stateDir = Join-Path $env:LOCALAPPDATA "zkstego\lnp22"
$publicRelation = Join-Path $stateDir "relation.json"
$privateWitness = Join-Path $stateDir "witness.json"
New-Item -ItemType Directory -Force $stateDir | Out-Null
$setup = go run . -fixed-setup -relation-out $publicRelation -witness-out $privateWitness | ConvertFrom-Json
$trustedRelationPin = $setup.relation_sha256
# The trusted verifier/operator must provision this pin independently; do not
# accept a relation digest supplied by an untrusted prover.
$sessionContextBindingHex = "<verifier-pinned-64-hex-policy-digest>"
$sessionDatabase = ".state/sessions.sqlite3"
$env:ZKSTEGOLNP22_SYNC_KEY_HEX = (py -3.12 -c "import secrets; print(secrets.token_hex(32))").Trim()
# The loopback issuer must already be running with the same database and
# independently pinned context binding.
$sessionGrant = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/v1/zkp/sessions
py -3.12 benchmark/lnp22_context_probe/video_e2e.py embed `
  --video data/encoded/coastguard_cif_q22_g1_3000f.h264 `
  --output benchmark/results/lnp22_video_e2e.h264 `
  --relation $publicRelation `
  --witness $privateWitness `
  --trusted-relation-sha256 $trustedRelationPin `
  --session-challenge-hex $sessionGrant.challenge `
  --report-output benchmark/results/lnp22_video_e2e_report.json
py -3.12 benchmark/lnp22_context_probe/video_e2e.py verify `
  --video benchmark/results/lnp22_video_e2e.h264 `
  --relation $publicRelation `
  --trusted-relation-sha256 $trustedRelationPin `
  --session-database $sessionDatabase `
  --session-context-binding-hex $sessionContextBindingHex
```

`$publicRelation`, `$privateWitness`, and `$trustedRelationPin` must come from
your separately provisioned setup; do not use the prover's report as the
verifier trust source. Keep `$privateWitness` in protected storage and never
publish it.

The report samples peak summed RSS for the Python process and its recursive
children at a nominal 100 ms wait interval. `rss_sampling_errors_observed` is
true and `rss_sampling_error_count` is nonzero if process access or measurement
errors may have caused undercounting; process-exit races are ignored. A false
error flag means only that no such errors were observed, not that every process
or peak was observed: short-lived spikes and processes born and exited between
samples can be missed. Intervals also include scan and scheduler time. This is a
single experimental run, not p50/p95 latency or real-time throughput. Runs
started before RSS instrumentation was added will not contain these RSS fields
and must not be described as measured for peak memory. The demo message is
public; the proof does not prove its commitment opening, the carrier contract
as an algebraic relation, or the H.264 encoder computation. The relation is marked
`unregistered-experimental-probe`; this experiment must not be accepted
by `src/zkp_registry.py` or cited as production ZKP integration.

An in-flight protocol-v2 run on the 3,000-frame input was started on
2026-09-28 at 02:37 local time. At the 06:44 status check it had written 16 of
30 carrier-segment files under
`benchmark/results/lnp22-video-e2e-widh37b4/`; it had not produced a final
video, extraction result, verification result, or report. This run started
before protocol v3 and RSS instrumentation, so it cannot validate v3 or report
the new measured peak RSS fields. Do not count it as a completed round trip
until its final video-only verification and strict decode finish successfully.
At the 06:45 check, FFmpeg `-v error -xerror` decoded the newest emitted
100-frame segment (`stego_00015.h264`) with exit code 0; this validates that
segment only, not the concatenated video or proof verification.
Earlier whole-video analysis reached about 10 GB working set, so memory
adequacy remains a practical concern for this input.
At the 07:27 status check, the same process (PID 37668) was still alive and had
written through `stego_00022.h264` (23/30 segments). Its instantaneous working
set was about 1.53 GiB; this is a process snapshot, not a sampled peak, and the
run still had no final video-only verification result at that time.
At 07:31 the process had advanced to 24/30 segments. The new
`stego_00023.h264` segment independently passed FFmpeg strict decode
(`-v error -xerror`, exit 0) and `ffprobe` reported 100 H.264 Constrained
Baseline frames at 352x288. This still says nothing about concatenated-video
decode or blind proof verification.
At 07:38 it had advanced to 25/30; `stego_00024.h264` also passed the same
strict-decode command and was reported as 100 Constrained Baseline frames at
352x288. PID 37668 remained live with about 1.55 GiB instantaneous working set;
this is not a peak-RSS measurement and the process predates RSS sampling.
At 07:42 the same PID was still live and had advanced to 26/30. The newly
written `stego_00025.h264` (3,286,669 bytes) passed FFmpeg strict decode
(`-v error -xerror`, exit 0); `ffprobe` reported 100 H.264 Constrained
Baseline frames at 352x288. This is segment-level decode evidence only: no
claim about the complete concatenated video, extraction, proof verification,
or protocol-v3 behavior follows from it.
At 07:47, FFmpeg strict-decode was run over all 26 emitted `stego_*.h264`
segments and all passed (zero decode failures). PID 37668 was still live,
with approximately 1.59 GiB instantaneous working set, but had not emitted a
new segment since 07:42; no final video or report was present. The successful
segment decodes do not establish that the concatenated stream decodes or that
blind extraction/proof verification succeeds.
At 07:48 the process had advanced to 27/30: `stego_00026.h264` was present
(3,196,718 bytes) and independently passed FFmpeg strict decode; `ffprobe`
reported 100 H.264 Constrained Baseline frames at 352x288. Thus all 27
currently emitted stego segments have passed strict decoding, but the output
video, extraction and proof verification are still pending.
The process was absent after the machine returned at 08:29. Windows event 1074
records a power-off initiated at 07:52:24 on behalf of the logged-in user, and
the Event Log service stopped at 07:52:33; the next boot was 08:29:48. The run
therefore ended with only 27/30 stego segments and no final video/report. This
is an interrupted run, not evidence of a pipeline exception or successful E2E
verification. Its partial artifacts are retained for diagnosis and must not be
counted as a completed benchmark.

After the reboot, a fresh run was started at 08:47 local time with PID 2884
(Python 3.12; launcher PID 28348), using the same 3,000-frame input
`data/encoded/coastguard_cif_q22_g1_3000f.h264` (SHA-256
`68d707171a2507993ac34ba755f913df5c8fb8131c5f878a2bccab29dead405`, H.264
Constrained Baseline, 352x288). New fixed-relation setup material was created
under `%LOCALAPPDATA%/zkstego/lnp22`; keep `witness.json` private. The run's
distinct output/report targets are
`benchmark/results/lnp22_video_e2e_retry_20260928T084753.h264` and
`benchmark/results/lnp22_video_e2e_retry_20260928T084753.json`, with separate
stdout/stderr logs. At 08:48 both Python and launcher processes were live; the
logs and final targets were still empty/not yet created. This retry remains an
experimental fixed-relation probe, not an audited application ZKP.
The loaded source identifies its transport as protocol v3
(`zkstego/lnp22-video-transport-probe/v3`); at 08:51 the Python process was
still live with the provisional proof artifact present in its temporary
workspace. That shows the retry passed its initial fixed-relation proof step,
not that video analysis, embedding, blind extraction, or final verification
has completed.
At 08:53 PID 2884 was still alive. Its context-analysis workspace contained
30 source segments (100 frames each); no stego segments had been written yet.
The process snapshot showed 329.8 seconds CPU time and 1.02 GiB working set.
These are instantaneous diagnostics, not measured peak RSS or a completed
performance result; the run was still in carrier/context analysis.
At 08:55:55 it remained in the same phase with the same 30 source segments
and no stego output. CPU time was 449.9 seconds and working set 1.19 GiB,
versus 329.8 seconds/1.02 GiB at 08:53:52. The snapshots imply continued
CPU-bound work and rising resident memory, but are not a sampled peak or a
completed performance measurement.
At 08:58:10 PID 2884 was still live with 30 source segments and no stego
segments. CPU time was 580.3 seconds and working set 1.54 GiB, another
instantaneous snapshot rather than peak RSS. The rising memory during this
stage is a resource-risk signal; the run has not yet produced its final report.
At 08:59:50 it was still active without stego output. Windows reported 679.2
CPU seconds, a current and OS-maintained process high-water working set of
1.71 GiB, and 2.30 GiB private commit. This high-water value covers this Python
process, not the recursive process tree or the final run; the instrumented
end-to-end RSS report is still pending.
At 09:03:54 it remained active with no stego output. PID 2884 had 912.5 CPU
seconds, a 1.95 GiB process working-set high-water mark, and 2.54 GiB private
commit. The host counter sample showed 1.21 GiB available, 26.97/43.63 GiB
committed, and 0 pages/sec at that instant. This single sample does not
guarantee future memory headroom; keep monitoring and do not interpret it as
the run's process-tree peak.
At 09:05:09 it was still active with no stego output. Current working set had
fallen to 1.33 GiB while the process high-water mark rose to 2.05 GiB; private
commit was 1.92 GiB and host-available RAM was 1.76 GiB. Memory is therefore
fluctuating rather than monotonically growing; no process-tree peak report is
available yet.
At 09:07:44, after about 20 minutes elapsed, PID 2884 remained live with 30
source segments and no stego output. CPU time had increased by 84 seconds over
the preceding 86 seconds, indicating active CPU-bound work rather than a
stalled process. Working set was 1.54 GiB, process high-water 2.05 GiB and
private commit 2.12 GiB. The full carrier-analysis stage is still incomplete.

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
16 framing bytes, the patcher confirmed the 459,792 positions requested by
that payload. The video had 4,332,560 raw safe candidates. The scan stops once
the requested number of positions has passed; therefore, the reported count is
a lower bound, **not total patchable capacity**, and does not establish zero
headroom. The report leaves `quality_validated` and
`blind_extraction_validated` false and did not write an embedded video. It
therefore establishes only that enough candidate positions passed the local
patcher gate for that exact artifact; it does not establish successful
embedding, visual quality, or blind verification.

The newer v4 artifact was measured separately in
`benchmark/results/streaming_patchable_capacity_lnp22_context_v4_coastguard_3000f_20260927.json`.
It is 57,415 bytes (SHA-256
`3f8f66334408988d457bb12480ece462fc927cee73399813cec14c0e89d7994a`). On the
same 3,000-frame Coastguard video, the 2,112.246-second scan confirmed the
459,448 positions requested by the proof plus 16 framing bytes. This is a
successful targeted patchability check, **not** a measured maximum capacity:
the tool stops at the target, and the raw safe-candidate count of 4,332,560 is
only a loose upper bound. No video was written, no decoder/quality test ran,
and blind extraction remains unvalidated.

The machine-readable reports generated by older scanner versions use the key
`patchability_capacity_assessment` for this target check. Do not interpret
that legacy field as an exhaustive capacity measurement; the scanner output
now reports `patchability_target_assessment` and states the target semantics
explicitly.

## Segmented blind-channel prototype

`src/blind_sync_streaming.py` adds a bounded-working-set transport for an
opaque payload: it divides bytes into versioned, ordered chunks, places one
chunk in each fixed-frame H.264 segment using the existing blind CAVLC channel,
and reassembles them from the output video. It requires exact segment frame
counts at the requested cuts, so inputs without IDR-aligned cuts fail closed.
The helper clears the process-local analysis cache between segments and
strict-decodes the concatenated result. Its tests are registered as Phases
25-26 in `src/runtest/run_all.py`.

A real 30-frame smoke test passed with a 30-byte diagnostic payload split over
three 10-frame segments. That smoke test alone validates only segmented
transport, not a full proof. **Status update (2026-09-28):** a subsequent
3,000-frame `video_e2e.py` run completed successfully with the full LNP22 proof
embedded in the H.264 output, strict decode, blind video-only extraction, and
proof verification (`valid: true`). See
`benchmark/results/lnp22_video_e2e_compact_20260928T1109.json` and the
standalone recheck `benchmark/results/lnp22_video_e2e_compact_20260928T1109.verify.json`.
This supersedes the earlier statement below that no full proof-on-video run had
passed. The relation is still an experimental pre-provisioned linear relation,
not an accepted application relation, and has not received independent
cryptographic review; this result is not a production lattice-ZKP claim.

## 2026-09-28 patchability performance recheck

The patchability validator now unpacks only the CAVLC block window plus its
existing 64-bit lookahead on the canonical path, instead of expanding the
complete RBSP for each candidate block. The rare non-canonical trailing-ones
fallback still expands the whole RBSP to preserve its predecessor checks. The
safety filter also reuses the source bit length only after the patchability
validator has successfully round-tripped that exact source block. CAVLC's
three immutable reverse-VLC lookup results are cached with a 1,024-entry bound.

On the same 30-frame fixture
(`data/external/trust_corpus/mdn_friday_cif_q22_g1_30f.h264`), forced
`load_or_build_video_analysis()` profiles with `cProfile` reported:

| Run | Total profiled time | Safe positions |
| --- | ---: | ---: |
| Before source-length reuse | 209.230 s | 180,966 |
| After source-length reuse | 201.860 s | 180,966 |
| After bounded VLC lookup cache | 185.800 s | 180,966 |

The latest profile is 23.430 seconds (about 11.2%) faster than the first
profile, with the same number of safe positions. This is an analysis-profile
comparison, not an end-to-end or real-time claim. The 3,000-frame Coastguard
context/capacity recheck took 700.573 s to select the required 10,296 carriers
for one 1,250-byte chunk; that measurement predates the bounded VLC lookup
cache and has not yet been repeated. It proves one chunk's targeted carrier
requirement only; it did not embed the proof, write a stego video, or run blind
verification. A real 30-frame segmented-channel smoke test passed in 165.01 s
before the lookup cache and 140.51 s after it, each with the diagnostic payload.
Those diagnostic runs did not validate a full LNP22 proof in video; the later
3,000-frame run cited above does, but took about 4 h 42 min end-to-end. The
measurements show that the current Python analysis/patchability path is far
from realtime on this host.

## 2026-09-28 decoded per-frame quality snapshot

`quality_report.py` creates a JSON report with per-frame Y/luma PSNR and SSIM,
segment hashes, measured coverage, and aggregate values. It uses `ffprobe` to
verify exact decoded frame counts and dimensions for each source/stego pair;
this avoids silently comparing only the shorter stream. The underlying shared
quality decoder forcibly resizes both streams to 352x288, so the report records
the original dimensions and explicitly discloses that resampling policy.

Command used on Windows PowerShell. The report explicitly bypasses frame-cache
reuse and passes the selected FFmpeg executable directly to each decoder:

```powershell
py -3.12 benchmark/lnp22_context_probe/quality_report.py `
  --run-dir benchmark/results/lnp22-video-e2e-widh37b4/zkstego-stream-vpw7jk0w `
  --output benchmark/results/lnp22_video_quality_v2_partial_finalcode_20260928T0720.json `
  --frames-per-segment 100 `
  --ffmpeg 'D:\Apps\ffmpeg\bin\ffmpeg.exe' `
  --ffprobe 'D:\Apps\ffmpeg\bin\ffprobe.exe'
```

The measured snapshot began at 2026-09-28 07:20 local time while the legacy
protocol-v2 E2E process was still running. It covers 22 of 30 source segments
(2,200 frames), with 8 segments unmeasured. For those measured frames, the
aggregate luma PSNR is 44.45678 dB, mean per-frame luma SSIM is 0.99961835,
and the lowest per-frame PSNR is 35.02782 dB; no frame had infinite PSNR. The
JSON includes every per-frame result and SHA-256 for each measured segment.
This is a partial, in-flight visual-quality measurement only: it does not prove
the ZKP, blind verification, tamper rejection, chroma quality, or quality for
the remaining segments. It compares the encoded source H.264 carrier to the
stego H.264 carrier after both are resized to CIF (352x288); it is not a
camera-original-to-encoded comparison. The run is protocol v2 and predates the
current protocol-v3 changes, so it is not v3 E2E evidence.

## E2E progress logs

New `video_e2e.py embed` runs emit flushed JSON Lines progress events to
standard error. Redirect stderr to a file to monitor a long run without
waiting for the final report. Events include the run/proof/context/embed and
blind-extract/verify phase boundaries, plus per-segment start/completion and
the strict decode gate. Each record contains a UTC timestamp and only an
allowlisted set of fields (phase, event, segment index/count, carrier count,
and error type); it must never contain the payload, proof, witness, sync key,
or private paths. The CLI report on standard output remains a final-result
artifact and is written only after the run finishes.

For example:

```powershell
py -3.12 benchmark/lnp22_context_probe/video_e2e.py embed `
  --video data/encoded/coastguard_cif_q22_g1_3000f.h264 `
  --output benchmark/results/lnp22_video_e2e.h264 `
  --relation $publicRelation `
  --witness $privateWitness `
  --trusted-relation-sha256 $trustedRelationPin `
  --session-challenge-hex $sessionGrant.challenge `
  --report-output benchmark/results/lnp22_video_e2e_report.json `
  1> benchmark/results/lnp22_video_e2e.stdout.log `
  2> benchmark/results/lnp22_video_e2e.progress.jsonl
```

The retry PID 2884 described above started before progress events were added,
so its empty stderr log is expected and it will not begin emitting JSONL
mid-run. Use the process/resource snapshots and the appearance of segment
artifacts to monitor that in-flight attempt; do not restart it solely to gain
progress output. The callback is observational and does not change carrier
selection, payload bytes, embedding decisions, or proof semantics. Unit tests
cover event ordering and enforce rejection of unapproved fields.

At 09:20 local time, PID 2884 was still live after about 33 minutes. It had
1,858.5 CPU seconds, 1.89 GiB current working set, and a 2.05 GiB process
working-set high-water mark. The context workspace still contained its 30
source segments and zero `stego_*.h264` outputs; final video, report, stdout,
and stderr remained absent/empty. This is evidence of ongoing CPU-bound work,
not a completed run or proof of a hang. The new progress callback was added
after this process started, so no progress JSONL is expected from it.

At 09:26 local time, the same PID was still live after about 38 minutes, with
2,189.5 CPU seconds, 1.92 GiB current working set, and 2.05 GiB working-set
high-water mark. The run still had zero stego segments, no final video/report,
and empty stdout/stderr logs. `py-spy dump --pid 2884` was attempted but could
not identify the target Python runtime on this Windows host; no stack was
captured and the process was left undisturbed.

The in-tree Go probe package passed `go test -race ./...` (7.735 s),
`go vet ./...`, and `go mod verify` on 2026-09-28. These are code-quality and
dependency-integrity checks only; they do not audit the cryptographic
construction or establish that it proves a useful video property.

At 09:30 local time, PID 2884 remained live after about 43 minutes, with
2,446.8 CPU seconds, 1.92 GiB current working set, and a 2.06 GiB process
working-set high-water mark. No `stego_*.h264` segments or final video/report
had appeared; the captured stdout/stderr logs remained empty. The increase in
CPU time confirms continued computation, but this run has not produced a
usable milestone and still has no live progress telemetry. A machine-readable
snapshot is preserved at
`benchmark/results/lnp22_video_e2e_retry_20260928T084753_status_20260928T023139Z.json`;
it deliberately records the attempt as incomplete and contains no witness or
key material.

## Experimental loopback HTTP API

`http_api.py` exposes the same experimental embed-and-verify and video-only
verify operations over an authenticated local HTTP channel. It is deliberately
loopback-only (default `127.0.0.1`), not a public service: it has no TLS,
multi-user authorization, durable job store, or cryptographically reviewed
application relation. Do not bind it to a LAN/public address. It accepts raw
H.264 uploads into an operator-controlled workspace and uses the relation,
witness, relation digest pin, and sync key provisioned in the server
environment. Neither secrets nor request bodies are written to access logs.

First create the workspace directories and provision the API token through a
secret manager/private shell environment. Keep the witness, relation pin,
sync key, and API token out of command history and reports:

```powershell
New-Item -ItemType Directory -Force '.\benchmark\api-data' | Out-Null
$apiWorkspace = (Resolve-Path '.\benchmark\api-data').Path
New-Item -ItemType Directory -Force `
  (Join-Path $apiWorkspace 'inbox'), `
  (Join-Path $apiWorkspace 'output'), `
  (Join-Path $apiWorkspace 'reports') | Out-Null
$env:ZKSTEGOLNP22_RELATION_PATH = $publicRelation
$env:ZKSTEGOLNP22_WITNESS_PATH = $privateWitness
$env:ZKSTEGOLNP22_TRUSTED_RELATION_SHA256 = $trustedRelationPin
$env:ZKSTEGOLNP22_API_TOKEN = (py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
$env:ZKSTEGOLNP22_SESSION_DATABASE = (Join-Path $stateDir 'sessions.sqlite3')
$env:ZKSTEGOLNP22_SESSION_CONTEXT_BINDING_HEX = '<verifier-pinned-64-hex-policy-digest>'
# ZKSTEGOLNP22_SYNC_KEY_HEX must also already be provisioned privately.
py -3.12 benchmark/lnp22_context_probe/http_api.py --workspace $apiWorkspace
```

Every route requires `Authorization: Bearer <token>`. The API provides:

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/health` | Authenticated liveness and experimental protocol label |
| `POST /api/v1/zkp/sessions` | Issue a verifier-bound, expiring one-use challenge |
| `PUT /api/v1/videos/{name}.h264` | Stream raw H.264 bytes into `inbox/` |
| `POST /api/v1/jobs` | Queue `embed` or video-only `verify` work |
| `GET /api/v1/jobs/{id}` | Read in-memory job status/result |
| `GET /api/v1/videos/{name}.h264` | Download an output H.264 file from `output/` |
| `GET /api/v1/reports/{name}.json` | Download its report from `reports/` |

Example client flow (run in a second shell with the same token provisioned):

```powershell
$headers = @{ Authorization = "Bearer $env:ZKSTEGOLNP22_API_TOKEN" }
$session = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8765/api/v1/zkp/sessions' -Headers $headers
Invoke-WebRequest -Method Put `
  -Uri 'http://127.0.0.1:8765/api/v1/videos/coastguard.h264' `
  -Headers $headers -ContentType 'video/h264' `
  -InFile 'data/encoded/coastguard_cif_q22_g1_3000f.h264'
$request = @{ operation = 'verify'; video = 'inbox/coastguard.h264' } |
  ConvertTo-Json -Compress
$created = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8765/api/v1/jobs' `
  -Headers $headers -ContentType 'application/json' -Body $request
$jobId = $created.data.id
$job = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/v1/jobs/$jobId" -Headers $headers
```

For embedding, submit `{"operation":"embed","video":"inbox/coastguard.h264","output":"output/stego.h264","report":"reports/stego.json","proof_mode":"compact","session_challenge_hex":"<challenge from session.data.challenge>"}`. The API checks that the challenge is currently active before starting the embed job. `proof_mode` may be `augmented` (default, v1) or `compact` (v2); the job response reports the selected mode, the embedded proof format, and `session_replay_protected:false` because the prover-side round trip does not consume verifier state. Then submit a separate video-only `verify` job; it extracts the challenge from the in-band envelope, validates the proof and context, and atomically consumes the session only on success. Expired, unissued, mismatched, failed-proof, and replayed sessions reject. The default limits are 512 MiB per upload, 2 GiB total inbox storage, 120 authenticated requests/minute, 2 job submissions/minute, and one active job. Busy submissions return `429`; output paths must be new files directly under their respective workspace folders. Job state is memory-only and disappears on server restart, but published output artifacts and the durable session database remain on disk.

The session store's policy-binding digest currently remains verifier-side
state; it is not a field in the experimental LNP22 proof statement. The proof
contains the issued session ID and video context, but this probe therefore
does not cryptographically prove the full registered application policy or
the target payload-opening relation. Do not treat successful session replay
checks as production ZK security.

The HTTP tests exercise actual loopback requests, session issuance, embed
challenge enforcement, verifier-owned replay consumption, streaming
upload/download, path confinement, authentication, quotas, rate limits,
status codes, and sanitized worker failures. They do **not** prove that the
experimental LNP22 relation is a useful or audited video ZKP, and synthetic
extractor tests do not substitute for a real-video proof-in-video E2E run.
The custom HTTP test runner passed 11/11 tests; the targeted prover-child
environment isolation test passed, Ruff passed for the API/test/runner files,
and Python compilation plus `git diff --check` passed on 2026-09-28. This
validates the API contract and local plumbing only, not real proof generation
through HTTP.

The Go prover/verifier child process explicitly does not inherit the blind
sync key, HTTP bearer token, or configured witness-path environment variable.
The HTTP API is still a single-operator local experiment: use a secret manager
for environment values, keep the listener on loopback, and do not treat these
controls as a production security review.

At 09:55 local time, the retry process was still alive after about 68 minutes.
It had 3,917.9 CPU seconds, a 1.99 GiB current working set, and a 2.06 GiB
working-set high-water mark. It still had zero stego segments, no final video
or report, and empty stdout/stderr logs. The current snapshot is preserved at
`benchmark/results/lnp22_video_e2e_retry_20260928T084753_status_20260928T025558Z.json`.

At 10:16 local time, PID 2884 remained CPU-active after about 88 minutes. It
had 5,124.3 CPU seconds, a 2.00 GiB current working set, and a 2.06 GiB
high-water mark. The process had split the input into 30 temporary context
segments, but still had no stego segments, final video, or report; stdout and
stderr remained empty. Live Python stack inspection was unavailable, so
`carrier_context_analysis` is only the phase from the last status snapshot,
not a claim about the exact current instruction. The timestamped observation
is preserved at
`benchmark/results/lnp22_video_e2e_retry_20260928T084753_status_20260928T031615Z.json`.
This remains an in-progress experiment and is not a completed benchmark.

At 10:25 local time, the same PID was still active about 98 minutes after
launch, with 5,679.7 CPU seconds and a 1.97 GiB working set (2.07 GiB peak).
The temporary context directory still contained the 30 split segments
(98,479,704 bytes total), while the run output directory still contained only
the 33,803-byte provisional proof. There was no final video/report and both
launcher logs remained empty. The host reported 1.7 GiB free physical memory;
a concurrent heavy integration test was deferred to avoid competing with this
run. The current status is recorded at
`benchmark/results/lnp22_video_e2e_retry_20260928T084753_status_20260928T032535Z.json`.

At 10:54 local time, PID 2884 remained active with 7,424.1 CPU seconds,
2.10 GiB current working set, and a 2.07 GiB high-water mark. Its temporary
context directory still held the same 30 source segments (98,479,704 bytes);
no stego segment, final video, or report existed, and the launcher logs were
still empty. This retry was launched before `--proof-mode compact` was added,
so it will continue using the default augmented/v1 proof path. Do not count
its CPU time or carrier analysis as proof embedding or video verification.
After wiring compact mode through CLI and HTTP, the video transport tests
passed 30/30, the loopback HTTP tests passed 7/7, Python compilation passed,
Ruff passed, and `git diff --check` passed. Those tests establish mode routing
and API contract behavior (the HTTP runner is mocked), not compact ZKP
embedding in a real video. A separate compact video run is still pending until
this active full-video attempt terminates or an explicit decision is made to
stop it.

At 10:57 local time, PID 2884 was still alive with 7,525.1 CPU seconds,
2.00 GiB current working set, and a 2.07 GiB high-water mark. The final video
and report still did not exist and both run logs were empty. This confirms
continued computation, not progress through a verified pipeline milestone.

At 11:03 local time, PID 2884 remained alive at 7,912.2 CPU seconds, with
2.00 GiB current working set and a 2.07 GiB high-water mark. The final video
was still absent. This process-specific check confirms the retry has not
terminated, but it still provides no usable E2E result.

At 11:08 local time, the owned v1 retry PID 2884 was stopped after more than
two hours because it had produced no stego segment, final video, or report;
its partial artifacts and empty logs were retained. The first compact launch
attempt (`...T1108`) exited immediately because Windows PowerShell treated
the JSONL progress stream on stderr as a terminating native-command error; it
created only empty logs and no Python process or video. A corrected attempt
(`...T1109`) launched at 11:09 with an ephemeral sync key held only in the
process environment. It generated its provisional compact proof in 2.8 s,
split all 3,000 frames into 30 segments, and began carrier selection at
segment 0 at 11:10. At 11:13, PID 19668 remained active at 170.1 CPU seconds
and 939 MiB current working set, with no completed segment or final artifact
yet. The progress log is
`benchmark/results/lnp22_video_e2e_compact_20260928T1109.progress.jsonl`;
this is ongoing carrier analysis, not an embedded-video or proof-verification
result.

At 11:16 local time, the compact run completed carrier selection for segment
0: 10,296 patchable carriers in 355 seconds (from the JSONL segment-start to
segment-completed timestamps). PID 19668 then advanced to segment 1; its CPU
time was 376.5 seconds and working-set high-water mark 1,295.7 MiB. This is a
real per-segment measurement from the full 3,000-frame attempt, not an
end-to-end latency or throughput result. It confirms the current selection
path is far from realtime at this operating point.

At 11:22 local time, carrier selection for segment 1 also completed with
10,296 carriers in 354 seconds. Segment 2 started immediately afterward.
PID 19668 showed 776.6 CPU seconds, 1,580 MiB current working set, and a
2,101 MiB high-water mark; host-available memory was 2,213 MiB at that
snapshot. These are process/host snapshots, not process-tree RSS sampling.

At 11:28 local time, segment 2 completed with the same 10,296 carriers in
353.9 seconds; segment 3 started. PID 19668 showed 1,178.4 CPU seconds,
1,818 MiB current working set, and a 2,103 MiB high-water mark. This retry
still runs the source loaded at launch, before the subsequent IDR-lookup
optimization; it is not an A/B result for that code change.

In `src/embedder.py`, `_prune_patchable_positions` previously searched the
descending IDR-offset list linearly for every candidate block. It now sorts
offsets ascending once and uses `bisect_right` to find the nearest preceding
IDR, reducing that lookup from O(blocks × IDRs) to O(blocks × log(IDRs)) while
preserving candidate order and IDR selection. Regression tests cover unsorted
IDR input and the exact preceding-IDR mapping; the focused patchability tests
passed 2/2, Phase 18 passed 1/1, Python compilation and targeted Ruff checks
passed. No runtime speedup is claimed until measured on a run that imports this
updated code.

At 11:32 local time, the compact run had entered segment 3 but had not yet
emitted its completion event. PID 19668 had 1,322.8 CPU seconds, about
1,934 MiB current working set, a 2,102 MiB process high-water mark, and the
host snapshot showed 1,748 MiB available. The CPU counter continued to rise;
no final video or report existed. This is an in-progress resource snapshot,
not a failure or a completed phase result.

At 11:34 local time, segment 3 completed carrier selection with 10,296
carriers in 372.2 seconds, then segment 4 started. The first four segment
selection durations were 355.0, 353.9, 353.9, and 372.2 seconds, respectively;
these are four within-run observations, not a representative latency
distribution. PID 19668 had 1,416.0 CPU seconds, 1,840 MiB current working
set, and a 2,105 MiB high-water mark. The progress JSONL still contains only
carrier-context events; embedding, extraction, verification, and final report
remain pending.

At 11:41 local time, the same compact E2E process (PID 19668) was confirmed
alive. Segment 4 completed with 10,296 carriers in 353.2 seconds
(04:33:57.222Z–04:39:50.443Z), and segment 5 had started. At the observation,
the progress log contained five completed carrier-context segments out of 30;
there was still no output video or report. This is continued carrier selection,
not evidence of proof embedding, blind extraction, proof verification, or a
completed video-level benchmark.

The current `_prune_patchable_positions` implementation also has a streaming
fast path when one modification per block is allowed: it validates unique
blocks in candidate order and stops when the required carrier count is met,
without first materializing a position list for every block. For larger
per-block limits it stores only up to that limit per block. A focused
regression test verifies order, deduplication, and that the one-per-block path
does not allocate the grouping `defaultdict`; the targeted patchability tests,
Phase 18 contract test, Python compilation, and targeted undefined-name/style
checks passed on the edited source. The in-flight PID imported its code before
this change, so no speedup or memory reduction is attributed to this process;
the optimization still requires a fresh, controlled measurement.

At 11:46 local time, the same process was still alive and had completed
segment 5 with 10,296 carriers in 356.5 seconds
(04:39:50.443Z–04:45:46.893Z); segment 6 had started. The first six measured
segments therefore range from 353.2 to 372.2 seconds each. At this rate the
remaining carrier-context scan alone is still a multi-hour operation; the
estimate is an extrapolation from six observations, not a completed runtime
measurement. The final video, report, embed stage, and video-only verification
remain pending.

At 11:52 local time, segment 6 completed with 10,296 carriers in 361.6 seconds
(04:45:46.893Z–04:51:48.525Z); the process remained alive and began segment 7.
Seven of 30 carrier-context segments were complete at that observation. This
confirms ongoing work, but the output video and report were still absent and
the proof had not yet reached the embed or blind-verification phase.

At 11:54 local time, `ffprobe` identified the input as H.264 Constrained
Baseline, 352x288, 25 fps. The first seven completed 100-frame
payload-bearing carrier-selection segments averaged 358.0 seconds each, about
0.28 frames/s within those selected segments. This was not the aggregate
carrier-context runtime: the video was split into 30 segments, but only 9
segments carried payload; the other 21 were hashed without carrier selection.
The complete `carrier_context` phase later measured 3,229.552 seconds
(04:09:46.932Z–05:03:36.484Z) for all 3,000 frames, or about 0.93 frames/s
overall. That is about 27x below the 25 fps input rate for this phase alone;
it excludes embedding, strict decode, blind extraction, and proof verification.
These are measurements of this run/configuration, not a general hardware or
end-to-end performance claim.

At 11:58 local time, segment 7 completed with 10,296 carriers in 359.3 seconds
(04:51:48.525Z–04:57:47.814Z), and segment 8 started. The run has now completed
8/30 carrier-context segments. The measured 0.28-frame/s figure above is
therefore still a carrier-selection-only rate; final embedding, strict decode,
blind extraction, and proof verification have not started.

At 12:04 local time, carrier-context derivation completed after processing all
30 input segments. Only indices 0–8 required carrier selection: indices 0–7
each selected 10,296 carriers and index 8 selected 3,864; indices 9–29 had no
payload carriers and were hashed. Final proof generation completed in 18.7 s.
Embedding then started, with 9 payload chunks scheduled across the 30 video
segments; the latest event is `embed/segment_started` for index 0. No final
video, report, strict-decode result, blind extraction, or verification result
has been produced yet.

At 12:10 local time, embedding segment 0 completed with 10,296 carriers in
359.7 seconds (05:04:08.986Z–05:10:08.712Z), and segment 1 started. This is
another single 100-frame segment measurement, not end-to-end throughput. It
shows that actual bitstream embedding is also taking about six minutes for
four seconds of 25-fps source footage on this run. The remaining 8 chunk
embeddings, strict whole-video decode, blind extraction, and proof verification
are still pending; do not extrapolate their measured latency until they run.

At 12:16 local time, embedding segment 1 completed with 10,296 carriers in
356.9 seconds (05:10:08.712Z–05:16:05.578Z), and segment 2 started. The first
two embed timings are 359.7 and 356.9 seconds for 100-frame segments. Segment
2 through 8, whole-video strict decode, blind extraction, and verification are
still pending; these two observations do not yet establish a latency
distribution.

At 12:22 local time, embedding segment 2 completed with 10,296 carriers in
355.4 seconds (05:16:05.578Z–05:22:00.997Z), and segment 3 started. The first
three payload-bearing segments therefore took 359.7, 356.9, and 355.4 seconds
each. Six payload chunks remain to embed, followed by strict whole-video
decode and the separate blind-extraction/verification pass; all are pending.

At 12:24 local time, a Windows CIM snapshot during embed segment 3 reported
913.6 MiB working set for Python PID 19668; the PowerShell/cmd/py launcher
processes together added about 87.3 MiB. The host reported 2,728 MiB free out
of 24,197 MiB visible physical memory. This is a point-in-time process snapshot,
not peak process-tree RSS and not the final sampler result from the run report.

At 12:28 local time, embed segment 3 completed with 10,296 carriers in
361.5 seconds (05:22:00.997Z–05:28:02.497Z), and segment 4 started. Four of
the nine payload-bearing segments are now embedded in the temporary candidate;
five remain, followed by whole-video strict decode and blind verification.

At 12:33:57 local time, embed segment 4 completed with 10,296 carriers in
354.805 seconds (05:28:02.497Z–05:33:57.302Z), and segment 5 started. Five of
nine payload-bearing segments are embedded; four remain. At 12:34:32, Python
PID 19668 was still alive at about 865.8 MiB working set. The output video,
report, strict decode, blind extraction, and proof verification are still
pending; this is a segment-level timing, not a completed E2E result.

At 12:41:05 local time, segment 5 had been running for about 427.7 seconds
without a completion event. PID 19668 was still alive; its CPU time increased
by 106.8 seconds between the 12:39:14 and 12:41:05 observations, and its
working set was about 1,201.9 MiB. This indicates continued computation but
also a longer-than-prior segment; it is an interim resource observation, not a
completed segment timing or peak-memory measurement. No final video/report,
strict decode, blind extraction, or verification result exists yet.

At 12:42:36 local time, embed segment 5 completed with 10,296 carriers in
519.047 seconds (05:33:57.302Z–05:42:36.349Z); segment 6 started. Six of nine
payload-bearing segments are now embedded, with three remaining. This segment
took materially longer than the preceding four measured embed segments. At
12:42:57, PID 19668 was still alive with about 810.9 MiB working set. These
single-run observations are not a latency distribution or peak-RSS result;
whole-video decode, blind extraction, verification, and final report remain
pending.

At 12:51:01 local time, embed segment 6 had run for about 505 seconds with no
completion event. The process remained CPU-active: measured CPU time rose by
about 60.6 seconds between 12:49:56 and 12:51:01; current working set was
about 1,109.5 MiB. This is another interim sample, not a completed latency or
peak-RSS measurement. The cause of the longer segment is not yet established.

Source-path review confirms the progress callback emits only segment-level
start/completion events. For each payload segment,
`embed_chunked_video_payload` calls `embed_blind_video_payload`, which analyzes
the segment, derives carrier positions, embeds bits, reconstructs the H.264
bitstream, and runs strict decode before returning. Consequently, the current
log cannot identify which of these substeps is consuming time inside segment
6; CPU activity alone must not be presented as proof that any specific
substep is progressing.

At 12:54:35 local time, embed segment 6 completed with 10,296 carriers in
719.213 seconds (05:42:36.349Z–05:54:35.562Z), and segment 7 started. Seven of
nine payload-bearing segments are now embedded; two remain. This is the
longest completed embed segment observed so far in this run. Whole-video strict
decode, blind extraction, proof verification, and the final report are still
pending.

At 13:06:31 local time, embed segment 7 completed with 10,296 carriers in
716.257 seconds (05:54:35.562Z–06:06:31.819Z), and segment 8 started. Eight
of nine payload-bearing segments are now embedded; segment 8 is the final
payload segment. Its runtime is not yet measured. Whole-video strict decode,
blind extraction, proof verification, and the final report remain pending.

At 13:18:05 local time, embed segment 8 completed with 3,864 carriers in
693.513 seconds (06:06:31.819Z–06:18:05.332Z). The complete embed-plus-strict-
decode phase ended at 06:18:06.114Z, taking 4,450.899 seconds from its logged
start at 05:03:55.215Z. The progress log then entered
`blind_extract_verify`; the standalone output artifact and JSON report are
published only after that verification phase returns, so neither is present
yet. Embedding and strict decode have passed, but blind extraction and proof
verification remain unconfirmed.

At 13:23:55 local time, `blind_extract_verify` had run for about 349 seconds
without another progress event. PID 19668 remained CPU-active: its CPU time
rose by about 53.9 seconds between 13:22:59 and 13:23:55; current working set
was about 949.5 MiB. The extraction API does not emit per-segment progress, so
this observation does not identify which internal verifier step is running.
The output video and report remain unpublished until the phase returns.

At 13:26:19 local time, `blind_extract_verify` had run for about 494 seconds
since its 13:18:06 start with no completion event. PID 19668 remained CPU-active:
CPU time rose by about 135.7 seconds since 13:23:55, and working set was about
1,089.2 MiB. This does not establish successful extraction or verification;
those results and the final artifacts are still pending.

At 13:28:21 local time, `blind_extract_verify` had run for about 615 seconds
since 13:18:06.114Z without a completion event. Python PID 19668 remained
active; CPU time increased by about 116.5 seconds since 13:26:19 and current
working set was about 1,187.9 MiB. No child process was present at that exact
snapshot. This is not evidence of a completed extraction or cryptographic
verification, and it does not identify which Python substep is running.

At 13:30:00 local time, `blind_extract_verify` had run for about 714 seconds
since 13:18:06.114Z. PID 19668 was still alive and CPU-active: CPU time rose
by about 54.6 seconds since 13:29:03; working set was about 1,247.5 MiB. No
verification completion event, output video, or final JSON report had appeared.

At 13:31:44 local time, the same verifier phase had run for about 818 seconds
since 13:18:06.114Z. PID 19668 remained alive; CPU time increased by about
54.2 seconds between 13:30:48 and 13:31:44, and current working set was about
1,315.2 MiB. No verification completion event or published artifact was
present; CPU activity is not a verification result.

At 13:33:28 local time, `blind_extract_verify` had run for about 922 seconds.
PID 19668 remained CPU-active; CPU time increased by about 63.5 seconds since
13:32:22. Python working set was about 1,623.6 MiB. The host reported about
1,991.9 MiB free out of 24,196.5 MiB visible physical memory. This is a
point-in-time sample, not peak RSS; verifier completion and final artifacts
remain pending.

At 13:35:47 local time, `blind_extract_verify` had run for about 1,062 seconds.
PID 19668 remained active; CPU time increased by about 65.7 seconds since
13:34:39 and working set was about 1,747.1 MiB. The host reported about
1,827.1 MiB free. This is another point sample, not peak memory; no verifier
completion event or published artifact was present.

At 13:38:10 local time, `blind_extract_verify` had run for about 1,204 seconds.
Across a 50-second sample, Python CPU time increased by about 47.1 seconds and
working set rose by about 39.6 MiB to 1,889.0 MiB; host free physical memory
was about 1,623.6 MiB. This confirms ongoing CPU work and rising memory across
that interval, but does not establish verifier success. No final artifact or
verification event was present.

At 13:39:27 local time, `blind_extract_verify` had run for about 1,281.9
seconds. PID 19668 CPU time increased by about 71.7 seconds since 13:38:10,
confirming continued CPU activity. Current working set was about 1,948.4 MiB;
the process high-water working set was about 2,109.5 MiB, and host free
physical memory was about 1,534.8 MiB. The process high-water value is an
interim OS sample, not the run report's process-tree RSS peak. Verification
and published artifacts remain pending.

At 13:40:31 local time, `blind_extract_verify` had run for about 1,345 seconds.
PID 19668 remained CPU-active (about 59.6 CPU seconds accrued since 13:39:27).
Its working set was about 1,997.2 MiB, private bytes about 2,613.2 MiB, and
OS process high-water working set about 2,109.8 MiB. Free physical memory
varied between about 1,177 and 1,510 MiB across two adjacent OS snapshots;
free virtual memory was about 16,204 MiB. These are interim process/system
samples, not the final summed process-tree RSS peak. No verifier completion
event or published artifact was present.

At 13:42:39 local time, `blind_extract_verify` had run for about 1,473 seconds.
PID 19668 CPU time increased by about 42.3 seconds over the preceding 44-second
sample, while working set had fallen to about 1,892.1 MiB from the earlier
2-GiB range; OS process high-water working set was about 2,114.3 MiB. Host free
physical memory was about 1,667.2 MiB. Resource values fluctuate; this snapshot
is not final peak process-tree RSS, and verification remains pending.

At 13:44:22 local time, `blind_extract_verify` had run for about 1,576 seconds.
CPU time increased by about 56.1 seconds over the preceding 58-second sample.
Working set was about 1,970.3 MiB, process high-water working set about
2,114.3 MiB, and host free physical memory about 1,570.4 MiB. No completion
event or output artifact had appeared; these measurements remain interim.

## Extraction progress instrumentation

The extractor now accepts an optional progress callback and emits
`segments_ready`, per-payload-segment `segment_started`/`segment_completed`,
and `segment_skipped` events for trailing video segments. The LNP22 E2E and
standalone verifier paths forward these redacted events to the JSONL progress
log. A test was first run against the unmodified API and failed as expected
(`progress_callback` was unsupported); after the change, the focused extractor
and verifier callback tests passed (2/2), and both edited Python modules passed
`py_compile`. This instrumentation was added after PID 19668 entered its
verification phase, so it does not add progress events to that in-flight run.

At 13:52:08 local time, the in-flight `blind_extract_verify` phase had run for
about 2,042 seconds. PID 19668 CPU time increased by about 64.6 seconds since
13:51:01, with current working set about 2,038.6 MiB and process high-water
about 2,114.3 MiB. Host free physical memory was about 1,504.2 MiB. The
progress log still had no extraction completion event, output video, or final
report; these are interim resource measurements only.

At 13:54:02 local time, `blind_extract_verify` had run for about 2,156 seconds.
PID 19668 CPU time increased by about 59.8 seconds since 13:53:00, confirming
continued work. Working set had fallen to about 1,715.1 MiB while the OS process
high-water remained about 2,114.3 MiB; host free physical memory was about
1,819.5 MiB. This is a fluctuating interim sample, not the final sampler result.
No verifier completion event or published artifact had appeared.

At 13:57:04 local time, `blind_extract_verify` had run for about 2,338 seconds.
CPU time increased by about 57.5 seconds across the 62 seconds since 13:56:02.
Working set was about 1,828.7 MiB, process high-water working set about
2,114.3 MiB, and host free physical memory about 1,713.8 MiB. The phase still
had no completion event, output video, or JSON report.

At 13:58:57 local time, `blind_extract_verify` had run for about 2,451 seconds.
CPU time increased by about 57.5 seconds since 13:57:04. Current working set
was about 1,844.3 MiB, process high-water working set about 2,114.3 MiB, and
host free physical memory about 1,650.9 MiB. No verification completion event
or output artifact had appeared; this remains an interim measurement.

At 14:01:06 local time, `blind_extract_verify` had run for about 2,580 seconds.
CPU time increased by about 55.9 seconds over the 59 seconds since 14:00:07.
Working set was about 1,878.1 MiB, process high-water working set about
2,114.3 MiB, and host free physical memory about 1,653.9 MiB. The log still
had no verifier completion event, output video, or final report.

At 14:03:00 local time, `blind_extract_verify` had run for about 2,694 seconds.
CPU time increased by about 59.7 seconds over the 61 seconds since 14:01:59.
Working set was about 1,947.2 MiB, process high-water working set about
2,114.3 MiB, and host free physical memory about 1,578.3 MiB. The verifier
still had no completion event or published artifact.

At 14:04:52 local time, `blind_extract_verify` had run for about 2,807 seconds.
PID 19668 CPU time increased by about 62.0 seconds across the preceding
64-second interval. Working set was about 2,035.4 MiB, process high-water
working set about 2,114.3 MiB, and host free physical memory about 1,482.7 MiB.
No verifier completion event or output artifact had appeared.

At 14:08:43 local time, `blind_extract_verify` had run for about 3,037 seconds.
PID 19668 remained CPU-active (CPU time 10,273.1 seconds; working set about
1,992.3 MiB; private bytes about 2,597.5 MiB). Host free physical memory was
about 1,472.8 MiB. The extractor's temporary directory contained all 30
100-frame H.264 segments, timestamped 06:18:14 UTC (13:18:14 local), eight
seconds after the verification phase began at 06:18:06 UTC. Splitting therefore
completed quickly; the subsequent blind parsing/extraction has not emitted a
segment event. The in-flight process predates the
progress callback instrumentation, so this absence does not identify which
segment is currently being parsed. No verifier completion event, output video,
or final report had appeared. These are interim OS samples, not final peak RSS.

At 14:16:18 local time, `blind_extract_verify` had run for about 3,492 seconds.
PID 19668 was still CPU-active (10,699.0 seconds cumulative CPU time); its
working set was about 2,054 MiB and private bytes about 2,659 MiB. Host free
physical memory was about 976 MiB. The JSONL log still had no extraction
segment-completion or verification event, and neither the output H.264 nor the
final report existed. This is an interim sample, not the sampler's final RSS.

At 14:25:38 local time, `blind_extract_verify` had run for about 4,052 seconds.
PID 19668 remained CPU-active (11,221.8 seconds cumulative CPU time), with a
working set of about 2,695 MiB and private bytes about 3,300 MiB. The host has
about 23.63 GiB visible physical memory, of which about 455.8 MiB was free at
this sample; free virtual memory was about 14.97 GiB. This is significant
physical-memory pressure, so keep monitoring before allowing the run to
continue indefinitely. The progress log still has no extraction completion or
verification event, and output video/report remain unpublished. These are
interim values, not the run's final process-tree RSS.

At 14:28:36 local time, PID 19668 remained CPU-active after about 4,230 seconds
in `blind_extract_verify` (11,389.2 seconds cumulative CPU time). Its working
set was about 2,832 MiB, private bytes about 3,436 MiB, and host free physical
memory about 860.1 MiB. No new extraction/verification progress or output
artifact appeared. Memory availability fluctuates; this is an interim sample.

At 14:35:41 local time, PID 19668 remained CPU-active after about 4,655 seconds
in `blind_extract_verify` (11,786.3 seconds cumulative CPU time). Its current
working set was about 3,317.5 MiB, OS high-water working set about 3,324.4 MiB,
private bytes about 3,995.7 MiB, and host free physical memory about 547.9 MiB.
No extraction-segment completion or verifier result had been appended; the
final output and report were still absent. Keep this classified as an active,
resource-intensive run, not as a pass; values are interim OS samples.

At 14:38:18 local time, PID 19668 remained CPU-active after about 4,812 seconds
in `blind_extract_verify` (11,931.2 seconds cumulative CPU time). Its working
set was about 3,361.5 MiB, process high-water working set about 3,389.0 MiB,
private bytes about 4,146.2 MiB, and host free physical memory about 692.7 MiB.
Free virtual memory was about 14,053.6 MiB. The JSONL log still had no
extraction or verification completion event; output video and report remained
absent. These remain interim process/system snapshots only.

## RBSP extraction allocation optimization

`extract_bits_direct` now reads only the needed RBSP bit window into packed
bytes instead of unpacking each whole NAL into a NumPy-backed `BitArray` for
every coefficient block. This avoids the prior per-block full-NAL allocation
and its roughly eightfold bit-array expansion, while preserving MSB-first bit
order, lookahead, and final-byte zero padding. The helper was checked against
the old slice-and-pack behavior in 6,400 deterministic randomized cases by a
read-only review; regression tests cover cross-byte offsets, clipped
64-bit-lookahead, and extraction order across two IDRs. Parser-reuse and SEC1
verification tests pass (14/14), and edited modules pass `py_compile`. This is
a measured semantic equivalence/allocation reduction, not a whole-pipeline
wall-time claim.
PID 19668 imported the previous code at launch and cannot measure this change.

A local helper-only microbenchmark used a synthetic 65,536-byte RBSP, a
46-bit requested window, 100 calls per sample, and the best of five samples.
The previous full `BitArray` unpack/slice/pack path took 0.005503 seconds; the
packed-byte window helper took 0.000144 seconds (38.2x for this isolated
operation). This does not measure H.264 parsing, block decoding, complete
extraction, proof verification, or end-to-end video throughput, and must not
be reported as a pipeline speedup.

The same helper-only comparison can be rerun from the repository root in
PowerShell (best of five samples, 100 calls per sample):

```powershell
@'
from timeit import repeat

from src.bitstream.bitstream_ops import BitArray
from src.core.pipeline import _rbsp_bit_window_to_bytes

data = bytes(range(256)) * 256
start_bit, end_bit = 1301, 1347

def previous(data, start_bit, end_bit):
    bits = BitArray(data)[start_bit:min(end_bit + 64, len(data) * 8)]
    bits.extend([0] * ((8 - len(bits) % 8) % 8))
    return bytes(
        sum(bits[index + offset] << (7 - offset) for offset in range(8))
        for index in range(0, len(bits), 8)
    )

assert previous(data, start_bit, end_bit) == _rbsp_bit_window_to_bytes(
    data, start_bit, end_bit
)
old_seconds = min(repeat(lambda: previous(data, start_bit, end_bit), number=100, repeat=5))
new_seconds = min(
    repeat(
        lambda: _rbsp_bit_window_to_bytes(data, start_bit, end_bit),
        number=100,
        repeat=5,
    )
)
print(f"old={old_seconds:.6f}s packed={new_seconds:.6f}s speedup={old_seconds / new_seconds:.1f}x")
'@ | py -3.12 -
```

Re-running this exact command produced `old=0.005489s` and
`packed=0.000144s` (38.1x for the isolated helper); small timing differences
from the earlier sample are expected on a shared, loaded host.

## Experimental payload-opening relation probe (2026-09-29)

`payload_opening_probe.go` and `payload_opening_probe_test.go` are an isolated
research probe, **not** the application prover/verifier or an accepted ZKP
backend. They replace the earlier unrelated fixed-witness relation with a
statement whose algebra actually depends on a 32-byte private payload:

```text
witness = (r0, r1, r2, bit[256], complement[256])
public  = (matrix_seed, context, commitment[2])
matrix   = Expand(matrix_seed, H(context))
commitment[i] = sum_j A_context[i,j]*rj + B_msg,context[i]*bit
              + B_ctx,context[i]*H(context)
bit[k] + complement[k] = 1; prover requests Beta=1 for witness coefficients
```

The bits use MSB-first byte order. **If** a proof enforced every witness
coefficient in `{-1,0,1}`, the complement equation would permit only
`(bit, complement)=(0,1)` or `(1,0)` coefficient-wise. The pinned verifier
does **not** establish that premise, as the counterexample below shows.
The verifier regenerates the matrix from its pinned 32-byte seed **and context
digest**, and rebuilds the full public LNP22 statement from the context and
commitment; it does not accept a prover-supplied relation. The seed in the
test is a deterministic fixture, not a production parameter-generation
ceremony. The public context is domain-separated and SHA3-256-digested, but the
caller must still construct
the canonical video/session/carrier context; this probe does not parse video.

Reproduce from this directory:

```powershell
go test -run '^TestPayloadOpeningProbe' -count=1 -v .
go test -count=1 ./...
go test -race -count=1 ./...
go vet ./...
```

On this host, the targeted run passed 3 tests and emitted an **actual
serialized experimental proof of 8,203 bytes**. The full Go module test suite,
its race-enabled run, and `go vet` also passed. The tests reject a reused
proof under changed context, commitment, or matrix seed; the case where both
context and commitment are shifted by the publicly known context term; a
changed payload with the original randomness; an out-of-bound bit witness at
the standard prover entry point; tampered proof bytes; and malformed
input shapes. These are one-run functional observations, not a latency
distribution or a security proof. The earlier real Coastguard transport used
10,779 carrier bytes, so this proof is smaller than that one envelope budget,
but it has **not** been embedded/extracted in a video.

**Confirmed blocking failure:** `lnp22_dependency_assessment_test.go` now
constructs the same Fiat-Shamir response while bypassing `ProveLinear`'s
prover-only `Beta=1` preflight. With the pinned parameters, a statement whose
first equation is exactly `s[0]=2` has no `Beta=1` solution, yet the canonical
serialized proof is accepted by `VerifyLinear`. A second test uses this
payload-opening probe's own matrix and a bit coefficient of 2 with complement
-1: the standard prover rejects it, but the serialized transcript is accepted
by the verifier. The latter test does not exclude an alternative in-bound
opening to that particular commitment; the former is the explicit false
`Beta=1`-statement counterexample. Consequently, the 8,203-byte proof cannot
be credited as proving valid payload bytes or an exact bounded opening. This
Go backend is **rejected for the target relation** unless a separate, sound,
reviewed boundedness proof is supplied. The original LNP22 paper is not
evidence that this pinned Go implementation enforces the same exact relation.

Other missing gates: the custom 2-row/3-random commitment has no reviewed
computational hiding/binding parameters or independent concrete security
estimate. The upstream `VerifyRange` and
two-ring paths have independently reproduced soundness defects, and the
library is a research dependency. The actual video context canonicalization,
session/replay policy, in-video envelope, blind extraction, malformed-proof
hardening, and security review are not connected to this probe. Do not use its
passing tests to claim the system goal is complete.

The context-and-commitment substitution test was added after a code review
found a real flaw in the first probe: with a fixed public matrix and only the
additive `B_ctx*H(context)` term, a third party could recenter `C` when
changing the context and reuse the exact same proof. The test failed as
expected against that first design. Deriving the experimental matrix from the
context digest makes the tested substitution reject, but this is only one
negative test, not a theorem or independent security review. The target
relation's stronger requirement is to absorb the complete canonical public
statement into the proof transcript before challenge generation.
