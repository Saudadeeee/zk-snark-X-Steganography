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

### WSL host capability check (2026-09-27)

The Windows host reports an Intel Core i7-12700H. The only registered WSL
distribution is Docker Desktop's internal `docker-desktop` distribution; it
is not a separate user-managed Linux development distribution. Reading its
`/proc/cpuinfo` flags returned `aes` and `avx2`, but not `avx512f`. The Docker
CLI also still cannot connect to `//./pipe/dockerDesktopLinuxEngine`.

This closes the local fallback check: the available WSL kernel is Linux
x86-64, but the AVX-512F prerequisite is not exposed, and the Docker engine is
unavailable. No LaZer build or proof execution was attempted. A suitable host
must expose AVX-512F and AES to the proof process; restarting Docker alone
would not address the missing AVX-512F flag observed in this WSL environment.

### Latest runtime preflight (2026-09-27)

The preflight was rerun from the current worktree with
`py -3.12 -m src.lazer_backend`. Docker's Linux x86-64 engine is available and
the inspected CPU flags include AES, but the container-visible flags still do
not include AVX-512F. The command returned:

```json
{"blockers":["avx512f_required"],"machine":"x86_64","ready":false,"system_name":"Linux"}
```

This supersedes the earlier `docker_daemon_unavailable` snapshot only for
Docker availability; it does **not** remove the AVX-512F blocker. No LaZer
container build, proof generation or verification was run in this check.

### Direct host CPU confirmation (2026-09-28)

The Windows host was queried directly with `Win32_Processor`; it reports an
Intel Core i7-12700H (14 cores / 20 logical processors). Intel's product
specification lists SSE4.1, SSE4.2, and AVX2 as the instruction-set extensions
for this exact SKU, with no AVX-512 entry:
[Intel Core i7-12700H specifications](https://www.intel.com/content/www/us/en/products/sku/132228/intel-core-i712700h-processor-24m-cache-up-to-4-70-ghz/specifications.html).
This agrees with the prior WSL/Docker flag checks: the available local host
cannot satisfy LaZer's documented AVX-512F prerequisite, regardless of
restarting Docker or changing the container image. This is a host capability
finding, not a LaZer build or proof test; no LaZer execution was attempted.

### Current runtime recheck (2026-09-28)

`py -3.12 -m src.lazer_backend` was rerun from the current worktree. The
Docker-visible environment reports Linux/x86-64 and `docker_available=true`,
but its CPU flag list does not include `avx512f`; the command exits 0 with
`ready=false` and blocker `avx512f_required`. No LaZer image build, proof
generation, or verification was attempted. This recheck confirms that the
current machine still cannot execute the pinned LaZer candidate; it does not
change the host prerequisite or the missing application-relation review.
The repository's custom contract suite also passed via
`py -3.12 src/runtest/test_lazer_backend.py` (6/6), including the missing-
AVX-512 fail-closed case. Pytest does not collect this file because the
project's test functions use its `t_` naming/custom runner convention.

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

An earlier LaZer preflight snapshot on this host returned
`{"blockers":["docker_daemon_unavailable"],"ready":false}`. That result is
historical; Docker later became available, while the current blocker is the
missing AVX-512F instruction as documented in the rechecks below. No LaZer
proof was built or run, so there is still no reviewed lattice-ZK backend
connected to the video pipeline.

### Carrier-map re-derivation probe

On the same Foreman CIF 150-frame input, an unvalidated one-byte smoke embed
was analyzed again from the resulting stego video. The output and machine
readable reports are preserved under
`tmp/goal-blind-probe-dpqjkz5v/` (`position_probe.json`,
`used_vs_rederived.json`, and `stego.h264`). The probe observed:

- Cover and stego analysis each produced 139,551 raw carrier candidates in
  identical order and with identical sets.
- Re-running patchability on cover and stego produced 576 candidates with the
  same set.
- The embedder used 320 positions. They were an order-preserving subsequence
  of the re-derived list, but not its first 320: the first difference was at
  candidate index 211, where `(36805, 14, -12)` was skipped by final
  reconstruction and later positions filled the payload budget.
- Analysis took 61.816 s for the cover and 62.098 s for the stego; embedding
  took 9.159 s. These are single cold-cache observations, not a benchmark
  distribution. This probe did not run strict decode validation.

This indicates that carrier discovery itself is stable for this sample, while
the set actually applied by reconstruction can omit positions. The signed
positions metadata currently records that omission. A video-only extractor
must either make reconstruction failures deterministic before embedding or
carry a recoverable skip map in an in-video bootstrap; assuming the first N
re-derived positions is incorrect. The packet currently has no such skip map.

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
the proof/verification timing, then implement a separately reviewed
application relation and embed the serialized proof into H.264 residual
carriers before routing any video through LaZer.

## Current host recheck (2026-09-28)

The preflight was rerun from the current worktree with
`py -3.12 -m src.lazer_backend`. Docker Desktop is now available and reports
20 logical CPUs; the Docker-visible assessment is Linux/x86-64 with AES, but
returns `ready: false` and the sole blocker `avx512f_required`. The Windows
host CPU reports Intel Core i7-12700H, which does not expose AVX-512F. Thus the
older wording that Docker itself is unavailable is stale; the current blocker
is CPU ISA compatibility. No LaZer build or proof run was attempted because
the guarded preflight correctly rejects this host. This does not change the
need for a supported runner and an independently reviewed application
relation.

The guarded command `py -3.12 -m src.lazer_backend --run` was also executed;
it exited 1 before invoking Docker, with
`RuntimeError: LaZer execution blocked: avx512f_required`. The official LaZer
README lists Linux x86-64, AVX-512 and AES as build/run requirements
([upstream README](https://github.com/lazer-crypto/lazer/blob/main/README.md)).
The upstream Labrador repository describes its code as research-only and not
security-reviewed or production-validated
([upstream Labrador README](https://github.com/lazer-crypto/labrador)).
