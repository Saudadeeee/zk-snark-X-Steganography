# Annex-B parser hot-path optimization (2026-10-01)

## Scope

This is a CPU timing diagnostic for the blind byte-extraction path, not a
proof-size, complete ZK, or realtime benchmark. It isolates two Python-level
NAL parsing helpers identified by cProfile: start-code scanning and removal of
H.264 emulation-prevention bytes. The change does not alter the CAVLC carrier
rule, encoder, proof system, envelope, or video.

## Fixture and host

- Input: existing `benchmark/results/native_pipeline_matrix_20260930T142913Z/deadline_cif_scaled_704x576/stego.h264`
- Source sequence: Deadline CIF Lanczos-scaled to 704x576; 1,374 frames,
  45.8458 s at 30000/1001 fps.
- H.264: Constrained Baseline/CAVLC, 2,840 NAL units, 11,520,665 bytes.
- Payload: one application byte (`a5`) inside the 15-byte `ZKVP` framing
  envelope; blind extraction returned that byte exactly.
- Host: Windows 11 Pro, Python 3.12.10, Intel Core i7-12700H, 23.63 GiB RAM.

## Results

The same in-process `extract_payload()` function parsed the same H.264 file
three times with the previous byte-by-byte helper implementations, then three
times with the optimized implementations. The old helpers were reproduced
in memory from the previous implementation; they were not written over the
working tree. Each run asserted that the result was exactly `a5`.

| Parser helpers | Three wall-time samples (s) | Median (s) | Relative to old |
|---|---|---:|---:|
| Previous byte-by-byte start-code scan and EPB removal | 19.171, 21.754, 21.732 | 21.732 | 1.00x |
| `bytes.find()` start-code scan and `bytes.replace()` EPB removal | 1.521, 1.498, 1.516 | 1.516 | 14.33x faster |

The median is about 3.0% of the 45.846-second source duration, but this
single-byte payload required parsing only enough carrier data to read the
framing header and payload. It does **not** imply proof-sized extraction has
the same latency. The separate 170,648-bit response extraction previously
measured at least 1,117 CPU seconds on the same project path; the target proof
format still does not exist.

The result is specific to this fixture and host. It is not an independently
randomized benchmark suite; the old implementation runs precede the optimized
runs, and memory was not re-measured for this diagnostic. The existing matrix
summary remains the source for its own peak-RSS values and must not be read as
measurement of this A/B run.

## Rejected CAVLC lookup experiment

After Annex-B optimization, a cProfile run made CAVLC block decoding the main
remaining cost. An 8-bit prefix lookup was prototyped to replace bit-at-a-time
trie traversal, then compared with the current trie decoder in alternating
order on the same payload/video. The six in-process samples were:

| Decoder | Samples (s) | Median (s) |
|---|---|---:|
| Existing trie | 0.763, 1.341, 1.617, 1.654, 1.700, 1.594 | 1.605 |
| 8-bit prefix table | 0.815, 0.802, 1.715, 1.743, 1.663, 1.576 | 1.619 |

The noisy medians show no measurable benefit (the lookup was about 0.9% slower
by median), so the experimental prefix-table code was removed. The committed
trie path remains in use; further CAVLC optimization needs a better measured
design, likely reducing per-symbol Python work without an unconditional
lookahead/rewind for each short VLC.

## Profile evidence

Before the change, a cProfile run counted 49,981,846 calls in 40.070 profiled
seconds: `_find_start_codes` took 10.744 s cumulative and
`_remove_emulation_prevention` took 24.548 s cumulative across 2,840 NALs.
After the change, the same profiled extraction counted 3,953,651 calls in
2.541 profiled seconds; NAL parsing took 0.049 s cumulative and trusted IDR
CAVLC extraction took 2.433 s. Profiling changes absolute timings, so the
unprofiled A/B table above is the timing comparison; the profiles identify the
remaining bottleneck as CAVLC block decoding.

## Reproduction and regression

The extraction command for the optimized source is:

```powershell
python native/x264_fork/tests/blind_extract_smoke.py `
  benchmark/results/native_pipeline_matrix_20260930T142913Z/deadline_cif_scaled_704x576/stego.h264 a5
```

For parser equivalence, `src/runtest/test_nal_parser_hotpath.py` compares the
optimized helpers with the previous loops over zero-run/start-code boundaries,
trailing prefixes, and all 256 possible bytes following an emulation-prevention
sequence. The real blind extraction also returned `PASS` after the change.
