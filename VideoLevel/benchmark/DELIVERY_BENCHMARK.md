# Current delivery benchmark index

This file points to the current measured suite. Legacy `SEC1`–`SEC7` JSON
datasets from the earlier proof-bearing pipeline were removed, their PNG charts on
2026-10-02, and their Python drivers (with the whole Python media pipeline) on
2026-10-03; they remain only in git history and do not define current numbers.

## Current artifacts

| Scope | Human-readable report | Machine-readable evidence |
|---|---|---|
| Performance and full-duration H.264 conversion | `results/performance_new.pdf` | `results/conversion_manifest_new.json`, `results/media_new/<run-id>/video_pipeline_new.json` |
| Per-frame visual quality | `results/video_quality_new.pdf` | `results/media_new/<run-id>/quality_per_frame_new.csv` |
| Cryptographic primitive comparison | `results/security_new.pdf` | `results/security_new.json` |
| Groth16 / PLONK proof comparison | `results/zkp_new.pdf` | `results/zkp_new.json` |

Use the commands and methodology in `NEW_BENCHMARKS.md` to regenerate the
current `_new` suite. The media embed/extract matrix is a 30-frame sample per
clip/resolution; only the source-to-H.264 conversion is full-duration. Upscaled
cases are derived from CIF clips, not native high-resolution footage.

## Interpretation limits

- Native CAVLC frame authentication uses a 16-byte truncation of HMAC-SHA-256.
  The Python HMAC comparison measures the full 32-byte primitive as a reference,
  not the native frame-tag timing or wire overhead.
- The ZKP benchmark proves the existing payload commitment statement, not camera
  origin or the entire video stream. Only Groth16 and PLONK have actual results.
- The old SEC5 artifact included simulated comparison values, and the old SEC6
  timing artifact came from a cache hit with zero-valued stages. Neither should
  be quoted as a current measurement.
