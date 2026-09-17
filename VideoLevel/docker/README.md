# Containerized execution

Build and run the native C/Python test and FFmpeg pipeline:

```bash
docker compose build pipeline
docker compose run --rm pipeline test
```

The Ubuntu image digest and direct Python requirements are pinned. Before a
cryptographic production release, replace `requirements.lock` with a fully
transitive hash-locked dependency file and install it with `--require-hashes`.

Run the LaZer hardware preflight through the pipeline image. This reads the
CPU flags visible to the container itself:

```bash
docker compose run --rm pipeline preflight
```

Only if that result has `"ready": true`, build and execute the source-pinned
LaZer smoke proof:

```bash
docker compose --profile lazer build lazer
python -m src.lazer_backend --run --image zkstego-lazer:10eafec
```

The `lazer` service is profile-gated on purpose. It must not be started on a
host without Docker-visible `avx512f` and `aes`; Docker cannot emulate those
instructions safely for this backend. The standard pipeline image excludes the
large local video corpus. For a user-owned run, mount a chosen input/output
directory explicitly with `docker compose run --rm -v /absolute/data:/work/data
pipeline shell`.

## AVX-512 capability diagnostic (QEMU/TCG)

On a development host without AVX-512, run this isolated emulator check:

```bash
docker compose --profile emulation run --rm avx512-qemu-diagnostic
```

It compiles a binary containing one AVX-512F vector addition and asks the
explicit QEMU/TCG process to run it, so the host does not execute that
instruction. The QEMU package is pinned to `1:8.2.2+ds-0ubuntu1.18`.

On the current image the expected diagnostic is `SIGILL` (exit 132): this QEMU
TCG build does not emulate AVX-512F. The service reports that result as a
successful diagnostic, not as a successful AVX-512 run. A newer or different
emulator can have a different result, so it is still only a best-effort
diagnostic. Use Intel SDE for functional instruction emulation, or a real
AVX-512F host for LaZer. Neither path supplies valid realtime or benchmark
figures.
