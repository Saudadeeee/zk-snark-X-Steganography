# Phase 5 candidate-analysis stage profile (2026-09-29)

## Scope

Single exploratory run on `data/encoded/akiyo_cif_q22_g1.h264` (4,074,416
bytes). It profiles the parser, IDR extraction, CAVLC safety filter and
patchability pruning used by the benchmark analysis path. It is not a full
Phase 5 API round-trip, repeated benchmark or end-to-end system result. RSS/USS
were sampled only at stage boundaries; the actual peak between markers may be
higher.

## Method

An inline Python 3.12 process called `H264BitstreamParser.parse()`,
`extract_all_idr_blocks(..., parser=parser)`,
`CAVLCSafetyFilter.get_safe_positions(..., frame_verified_data=...)`, and
`_prune_patchable_positions(..., required_bits=424)`. The process logged
`psutil.Process().memory_info().rss` and
`memory_full_info().uss` at each stage. The target matches the Phase 5 test
message framing. No code or benchmark selection was changed for this run.

## Observations

| Stage | Cumulative time | RSS | USS | Output shape |
|---|---:|---:|---:|---|
| H.264 parse | 2.35 s | 0.040 GiB | 0.026 GiB | 901 NAL units |
| IDR extraction | 78.84 s | 1.764 GiB | 1.754 GiB | 995,670 macroblock records; 300 IDR frames; 1,570,116 entries in each of `nC_map` and `nal_length_map` |
| Full safety-position enumeration | 340.69 s | 2.391 GiB | 2.385 GiB | 1,636,667 safe coefficient positions |
| Patchability prune | 345.04 s | 2.391 GiB | 2.385 GiB | 424 retained positions |

Elapsed time is cumulative; derived intervals are approximately 76.5 s for IDR
extraction, 261.9 s for safety enumeration and 4.35 s for pruning. Safety
enumeration dominates this run. Extracted per-block metadata accounts for most
of the measured memory increase. A small compressed input therefore does not
imply cheap analysis: this CIF clip expands into nearly one million macroblock
records and over 1.5 million offset-map entries.

## Interpretation and next diagnostic

Trying this smaller clip first may avoid scanning larger candidates, but does
not solve the analysis cost: this single-clip run took about 5 minutes 45
seconds and reached at least 2.39 GiB USS before embedding or verification.
Changing candidate order alone is not evidence of low-memory or realtime
operation.

The next optimization to evaluate is bounded/streaming carrier analysis that
stops after enough positions pass the exact patchability and forward-decode
rules, with an explicit fallback to continue scanning when capacity is
insufficient. Preserve deterministic carrier order and fail closed on partial
analysis. Test both successful and insufficient-capacity cases; ensure
total-capacity benchmark code remains exhaustive. Differentially compare
positions and embed/verify results against exhaustive analysis on fixed clips.

No Phase 5 asset order or runtime behavior was changed based on this profile.

## Carrier-order constraint found during optimization review

`CAVLCSafetyFilter.get_safe_positions()` exhaustively gathers ordinary and
trailing-one sign carriers, then returns
`sort_blocks_interleaved(safe_positions, _CIF_MB_COUNT)`. This ordering
round-robins frames and reorders macroblocks inside each frame. A small live
check with two candidate positions in frame 0 and one in frame 1 produced:

```text
raw first two:        [(0, 1, 5), (0, 2, 6)]
exhaustive order:      [(0, 2, 6), (396, 1, 7), (0, 1, 5)]
exhaustive first two:  [(0, 2, 6), (396, 1, 7)]
```

Therefore a simple early `break` while scanning source blocks and returning
the collected positions would alter the embedding/extraction order; it is not
a safe drop-in optimization. A bounded implementation must produce the same
prefix as the exhaustive sorted order (including trailing-one sign carriers),
or introduce an explicitly versioned carrier-order profile implemented
identically by blind extraction and verification. Add differential tests
before using such a profile for real proofs/payloads.
