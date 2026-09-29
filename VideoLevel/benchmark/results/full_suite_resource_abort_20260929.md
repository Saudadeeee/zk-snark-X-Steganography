# Full-suite resource-limited run (2026-09-29)

## Run and outcome

- Command: `py -3.12 src/runtest/run_all.py`
- Runtime preflight immediately beforehand: `py -3.12 -m src.lazer_backend`
  reported Linux/x86-64, AES and Docker available, but `ready=false` because
  `avx512f_required`.
- The suite reached `src/runtest/test_phase5_extract_verify.py`. Its parent
  Python process was PID 8016; test process PID 21148. The test process was
  CPU-active and its working set grew throughout the run.
- I sent Ctrl+C to the exact exec session when available physical RAM fell to
  1.4 GiB. The Python processes exited and available RAM recovered to 6.71 GiB.
- No Phase 5 summary or full-suite exit status was emitted before cancellation.
  This run is **incomplete**, not a pass or a test failure verdict.
- `data/output/test_p5_*` files observed after cancellation have timestamps
  2026-09-27, not this run. No new partial Phase 5 video was found.

## Observed resource samples

Samples were read from Windows process counters while the test ran. They are
coarse observations, not a benchmark distribution or isolated peak-RSS test.

| Approximate elapsed phase time | Test process working set | Host free RAM |
|---:|---:|---:|
| ~1 min | 1.10 GiB | not sampled |
| ~1.5 min | 1.23 GiB | 4.81 GiB |
| ~2 min | 2.05 GiB | 4.12 GiB |
| ~2.5 min | 2.70 GiB | 3.53 GiB |
| ~3 min | 3.63 GiB | 2.64 GiB |
| ~3.5 min | 4.36 GiB | 2.61 GiB |
| ~4 min | 5.03 GiB | 2.03 GiB |
| ~4.5 min | 5.45 GiB | 1.67 GiB |
| ~5 min, cancellation threshold | 5.76 GiB | 1.40 GiB |

## Interpretation and next action

This confirms a substantial resource-growth issue in the current public-API
Phase 5 exercise on its selected high-capacity video path. The evidence does
not yet identify whether peak memory comes from candidate analysis, embedding,
reconstruction, or verification; the runner's buffered output did not expose
the active subtest before cancellation. Do not rerun the same unbounded suite
on this host. Next isolate one subtest and instrument per-stage RSS/cache size
with a strict memory ceiling or use a smaller representative clip first.
LaZer execution remains unavailable on this host without AVX-512F.
