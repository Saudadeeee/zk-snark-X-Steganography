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
