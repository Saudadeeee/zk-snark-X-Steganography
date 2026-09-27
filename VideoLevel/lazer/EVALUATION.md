# LaZer integration evaluation

Date: 2026-09-17

## Current machine result

The Docker amd64 preflight completed successfully enough to inspect the guest
CPU. It reported Linux/x86-64 and `aes`, but did **not** report `avx512f`.
`python -m src.lazer_backend` therefore returned:

```json
{"blockers":["avx512f_required"],"docker_available":true,"machine":"x86_64","ready":false,"system_name":"Linux"}
```

Consequently no LaZer image was built or run here. This is expected: a Docker
container cannot add an AVX-512 instruction set that the host does not expose.

## Current-machine recheck (2026-09-27)

The preflight was rerun after checking the local Docker CLI and engine. The CLI
is installed, but `docker info` cannot connect to the Docker Desktop Linux
engine. The updated `python -m src.lazer_backend` result is:

```json
{"blockers":["docker_daemon_unavailable"],"cpu_flags":[],"docker_available":false,"machine":"","ready":false,"system_name":""}
```

Because the engine is unavailable, this run did not inspect container-visible
CPU flags. In particular, it does not confirm or supersede the earlier
AVX-512F result; restore the engine and rerun the preflight before attempting
any LaZer build or proof execution.

## Alternative implementation check (2026-09-27)

No inspected alternative is currently a justified production replacement for
the pinned LaZer candidate:

- [Lattirust](https://github.com/lattirust/lattirust) contains lattice-ZK
  building blocks and LaBRADOR/LOVA implementations, but its own README says
  it is for research/prototyping, has not been audited, and is not fit for
  real-world deployment.
- [Lazarus](https://github.com/lattice-complete/Lazarus) has lattice-ZK
  components, but its README says the API is under active development and
  explicitly says not to use it in production.
- [LNP22 Go](https://github.com/KarpelesLab/lnp22) advertises a NIZK for short
  linear relations and could be a CPU-portable experimental candidate. Its
  repository is small and does not establish an independent audit or bind the
  project's video statement, carrier policy, and payload; do not enable it as
  a production backend without those reviews and relation work.

These source-level checks do not establish cryptographic security. The current
environment blocker and missing application-specific relation remain; changing
libraries would not by itself make the embedded-video ZKP complete.

### LNP22 execution probe

An isolated checkout of `KarpelesLab/lnp22` at commit
`878cf9d5bf73ae387b73a0843edc3364fd0f6be4` was tested outside the project
worktree with Go 1.26.2 on Windows/amd64:

| Measurement | Observed result |
|---|---:|
| `go test ./...` | 10 packages passed |
| One default-parameter linear-relation proof JSON | 15,647 bytes |
| Public statement JSON (`A`, `t`) | 48,400 bytes |
| One proof-generation run | 5.643 ms |
| One verification run | 2.884 ms |
| Upstream verifier result | `valid=true` |

This was one smoke measurement, not a benchmark distribution. The witness and
statement were generated as `t = A*s` by the upstream example pattern. It does
not prove a payload, video, H.264 embedding policy, or provenance statement;
the statement size is not included in the proof JSON and must be provisioned
independently. The repository's green tests and this probe do not establish an
independent cryptographic audit. Treat these numbers only as an experimental
size/runtime feasibility point, not as an accepted system backend.

### In-repository SIS prototype size probe

On 2026-09-27, `LatticeZkProof.create(b"x", b"k" * 32)` generated one
`sis-linear-fiat-shamir-v1` transcript in 0.159 seconds. Its canonical JSON
artifact was 131,692 bytes (1,053,536 bits): the base64 `responses` field alone
was 87,384 bytes and `commitments` was 43,692 bytes. This is a single
measurement, not a performance benchmark, and this prototype is explicitly not
an accepted or independently reviewed ZKP backend.

For `foreman_cif_q18_g1_150f.h264`, the recorded raw safe-carrier count is
139,551 bits. Even treating every raw candidate as usable gives an upper bound
about 7.55 times smaller than that prototype's JSON transcript, before adding
any payload framing. The actual patchable/FFmpeg-clean capacity is lower. This
does not establish impossibility for every video or every proof system; it
does establish that this prototype cannot be embedded in that measured video
under the current carrier representation. The separate one-byte FFmpeg smoke
run embedded 320 payload bits using 576 FFmpeg-validated candidates, of which
400 passed patchability filtering; strict FFmpeg decode returned exit code 0
with empty stderr. That output was temporary and the run was not a repeatable
benchmark artifact.

A follow-up real-video commitment check on the same one-byte payload took
163.908 seconds for `embed(..., ffmpeg_validate=True)`. It embedded 320 bits,
reported 576 FFmpeg-validated and 400 patchable carriers, recomputed the
statement commitment successfully from the output video and returned carrier
list, and rejected the same check with one carrier removed. A separate strict
FFmpeg decode returned exit code 0 with empty stderr. This is one instrumented
smoke run, not a latency distribution; the output and keys were temporary.
The emitted manifest identified the backend as `ml-dsa-65-attestation`, so
this verifies commitment consistency only, not a lattice-ZK proof or
video-only blind extraction.

The current LaZer preflight on this host returned
`{"blockers":["docker_daemon_unavailable"],"ready":false}`. No LaZer proof
was built or run, so there is still no reviewed lattice-ZK backend connected
to the video pipeline.

## What is integrated

- Immutable upstream pin: `10eafeca4cd53ff4fc54193dce904dbd0026fefd`.
- Linux container recipe that builds LaZer and its `python/demo` proof of the
  general relation `A*s=t`.
- Runtime preflight that fail-closes unless Linux, x86-64, AES, AVX-512F, and
  Docker are present.
- CI unit contracts for source pinning and host gating.

## What is deliberately not claimed

LaZer is not called from `embed()` or `verify()`. The upstream demo is a
general lattice relation, not yet the project relation binding payload,
positions hash, stego hash, and an independently registered public statement.
No claim of a video lattice-ZKP, video quality change, capacity change, or
real-time proving performance is valid until that relation, serialization, and
end-to-end AVX-512 fixture run are implemented and reviewed.

## Readiness assessment

| Area | Status | Reason |
|---|---|---|
| Source reproducibility | Partial | Git revision and base image are pinned; container build is unverified on this host. |
| Local execution | Blocked | Visible CPU lacks AVX-512F. |
| Video pipeline integration | Not started | No reviewed application relation yet. |
| Security claim | Not approved | LaZer and the application protocol require independent review. |
| Real-time claim | Not evaluated | Needs an AVX-512 target and a per-GOP measurement. |

The next valid execution target is a Linux x86-64 host exposing `avx512f` and
`aes` to Docker. On that target, run the commands in `lazer/README.md`, save
the proof/verification timing, then implement a separately reviewed sidecar
relation before routing any production video through LaZer.
