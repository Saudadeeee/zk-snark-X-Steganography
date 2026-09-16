# LaZer research backend

This directory pins LaZer to the source revision in `LAZER.lock.json` and
builds its documented general linear-relation demo: `A*s=t`.

It is intentionally **not** connected to `embed()` or `verify()`. LaZer is a
research library and this project does not yet define, parameterize, serialize,
or externally review a lattice proof relation for the video protocol.

## Target host

Run only on Linux x86-64 with `avx512f` and `aes` CPU flags. Check the exact
flags visible from Docker first:

```bash
python -m src.lazer_backend
```

Only when it returns `"ready": true`, build the source-pinned container:

```bash
docker build -t zkstego-lazer:10eafec -f lazer/Dockerfile .
python -m src.lazer_backend --run --image zkstego-lazer:10eafec
```

The demo accepts only its own example relation. Replacing it with a video
sidecar requires a reviewed protocol that binds an independently registered
public statement to a defined payload/position/hash policy.
