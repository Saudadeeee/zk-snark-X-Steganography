# LaZer execution-host recheck (2026-09-29)

## Executed commands

```powershell
py -3.12 -m src.lazer_backend
py -3.12 -m src.lazer_backend --run
```

The preflight JSON reported `docker_available=true`, `system_name=Linux`,
`machine=x86_64`, and `ready=false`, with the sole blocker
`avx512f_required`. The visible CPU flags include AES and AVX2 but not AVX-512F.
The guarded run raised `RuntimeError: LaZer execution blocked:
avx512f_required` before it launched the pinned demo container. No image build,
proof generation or proof verification occurred in this check.

## Upstream compatibility evidence

- The pinned [LaZer README](https://github.com/lazer-crypto/lazer/blob/main/README.md)
  lists Linux amd64/x86-64, AVX-512 and AES among build/run requirements.
- The original [Labrador README](https://github.com/lattice-dogs/labrador)
  says that implementation can only be compiled and run on CPUs supporting
  AVX-512.
- The [Lattirust Labrador README](https://github.com/lattirust/labrador)
  says binary/ring R1CS reductions are still in progress. The parent
  [Lattirust README](https://github.com/lattirust/lattirust) says it is for
  research/prototyping and has not been audited; local test failures are
  separately recorded in `PQ_VIDEO_ZKP_PLAN.md`.

## Conclusion

Docker is not the blocker; the instruction set visible to the proof process is.
There is no evidence here of a supported portable build mode for LaZer or the
original Labrador implementation. Do not bypass the hardware gate or treat
the incomplete Rust port as an accepted substitute. An AVX-512-capable runner
would clear only the local execution prerequisite; the application relation,
security review, serializable proof, in-video embedding, and blind verification
remain unimplemented/unverified.
