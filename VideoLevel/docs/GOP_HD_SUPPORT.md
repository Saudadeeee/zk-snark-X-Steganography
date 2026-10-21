# GOP > 1 and HD streams (roadmap B3)

Status: GOP > 1 Baseline streams (IDR + P slices) are supported behind a new
GOP policy of the carrier profile; 720p/1080p all-intra streams, including
several slices per picture, parse and recompute their carriers. All-intra
behaviour is byte-identical to commit `dddb9d5` (carrier positions, video
digest, stego bytes and all-intra carrier-profile ids, pinned by
`src/runtest/test_gop_and_hd_support.py`).

## What happened before this change

Measured on the `dddb9d5` code with CIF clips encoded with `-g 8` and `-g 25`:

* **Analysis** parsed only IDR NAL units. P slices were skipped but advanced
  the picture counter, so carrier coordinates stayed `picture_index x MBs +
  mb`; nothing was rejected or misparsed.
* **Patching** rewrote only IDR slices; every other NAL unit was written back
  from its RBSP. P slices came out byte-identical (175/175 on container g8).
* **Canonical digest** hashed every non-IDR NAL unit's header fields and RBSP
  raw, so P slices were already bound, except for one malleability: the parser
  strips every `00 00 03`, so a superfluous emulation-prevention byte changed
  the file but not the digest.
* **Segmentation** (`ffmpeg -f segment -segment_frames 100,200,...`) cuts only
  at key frames. With GOP 8 a cut at frame 100 moved to 104 and the frame-count
  check failed closed ("choose boundaries aligned to IDR frames"); with GOP 25
  or `frames_per_segment` a multiple of the GOP it worked.
* **Statements** did not distinguish the stream structure: a GOP > 1 video
  verified under the same carrier profile as an all-intra one.
* **Several slices per picture** parsed (each slice NAL got its own
  picture-sized coordinate slot), but the transport globalised positions with
  `frame_offset x MBs`, so with `k` slices per picture the slots of segment
  `i` overlapped those of segment `i+1`.

## What is supported now

### GOP policy (`src/gop_policy.py`)

`CarrierProfile(..., gop_policy=...)` in `src/lattice_zk/video_pipeline.py`:

| policy | streams | carriers | other NAL units |
|---|---|---|---|
| `all-intra` (default) | every coded slice is IDR | IDR luma 4x4 blocks | raw RBSP in the digest |
| `idr-carriers-inter-raw-v1` | Baseline GOP > 1: IDR, P and non-IDR I slices | IDR luma 4x4 blocks only | raw RBSP in the digest |

Every transport segment (cover at embedding, stego at extraction, carrier
and raw-hashed segments alike) is checked from its Annex B bytes before any
analysis; violations raise `ValueError`, which the verifier reports as
`valid=False`:

* the first coded slice of each segment is an IDR slice (so every cut is an
  IDR access unit and no segment references a picture of another), and the
  number of pictures equals ffprobe's decoded frame count;
* `all-intra`: no non-IDR slice at all (so a GOP > 1 stream is refused under an
  all-intra profile, with a message naming the GOP policy);
* only I and P slices (no B, SP, SI), no data partitioning, no arbitrary slice
  order, no picture mixing IDR and non-IDR slices, `first_mb_in_slice` inside
  the picture, no slice groups (FMO), no redundant pictures, no CABAC; a
  progressive Baseline SPS (`profile_idc` 66, `frame_mbs_only_flag` 1); SPS/PPS
  identical within a segment and present before the first slice;
* no bytes outside NAL units (before the first start code, or a start code
  without a NAL unit);
* canonical emulation prevention in every NAL unit (escaping exactly the
  minimal one of its RBSP), and `forbidden_zero_bit = 0`. With this, RBSP
  equality is NAL byte equality, so the digest binds every P-slice byte.

The policy is part of the carrier profile id only when it is not the default:

```text
profile description += {"gop_policy": "idr-carriers-inter-raw-v1"}
```

so a GOP > 1 statement has a different `carrier_profile_id`, policy hash,
relation id and registry entry than an all-intra one, and all-intra ids are
unchanged. `codec_policy_id` is unchanged. This is the only change in
`src/lattice_zk/` (no cryptographic code is touched).

### Digest rules

Unchanged formula (`docs/LATTICE_ZK_BDLOP_SPEC.md` 3.6). Per carrier segment:
IDR NAL units with carriers contribute their RBSP bits between carrier blocks
plus the normalised carrier blocks; every other NAL unit, in particular each P
slice, contributes its header fields and full RBSP. Segments without carriers
are hashed as files. Changing one bit of any P slice changes `D` (tested at
the digest level and end to end).

### Segmentation

Segments stay fixed-length (`frames_per_segment`, bound in the profile). For
GOP > 1 choose a multiple of the GOP length (e.g. 104 or 200 for GOP 8, 100
for GOP 25); any other value fails closed. Segments are therefore whole GOPs.
Because only IDR pictures carry, the capacity of a segment is
`frames_per_segment / GOP` IDR pictures; longer segments do not cost memory
(P slices are never parsed).

### Several slices per picture

Each coded slice keeps its own picture-sized coordinate slot (as the analysis
already did), and the transport now offsets each segment by the number of
coded slices before it instead of the number of frames. For one slice per
picture the two are equal, which is why single-slice output is byte-identical.
Multi-slice streams get different (now collision-free) global positions, hence
a different `positions_hash`, than under `dddb9d5`; the stricter structure
checks also refuse streams `dddb9d5` accepted (non-canonical escaping, bytes
outside NAL units, changing parameter sets, non-Baseline SPS). x264 output
passes all of them.
Slices restart CAVLC neighbour contexts, which the parser already does per
NAL unit. x264 emits one slice per picture unless `slices=N`,
`slice-max-size` / `slice-max-mbs` or sliced threads (e.g. `-tune
zerolatency`) are used.

### HD

* MB count from the SPS (`80 x 45` at 720p, `120 x 68` at 1080p); cropping
  (1088 -> 1080) only affects display and is left to the decoder.
* Level limits: x264 picks Level 3.1 (720p) / 4.0 (1080p); nothing in the
  parser depends on the level.
* The stable-carrier analysis already used the SPS MB count (earlier fix,
  `test_non_cif_carrier_capacity.py`). The embedding-order heuristics of the
  original contracts (`sort_blocks_interleaved`, the chaos shuffle's
  bottom-row preference) still assume a CIF grid of 22 x 18; at 4CIF/HD they
  only change the deterministic order, identically at embedding and
  extraction, not correctness. The `*-geo` contracts order the same carriers
  on the SPS grid; see "Resolution-aware carrier order" below.

### Resolution-aware carrier order (stream C4)

**Inventory** of CIF geometry hard-coded in the carrier path (`22`, `396`,
`18`, `cif_mb_count`, `mb_width`, `macroblocks_per_frame`):

| place | constant | class | status |
|---|---|---|---|
| `core/analysis_cache._build_serial_analysis`, `core/parallel_analysis` jobs | `cif_mb_count` (IDR offset of a block) | correctness | SPS count (earlier fix); `396` only as a fallback when the context has none |
| `core/stego.CAVLCSafetyFilter.get_safe_positions` | default `cif_mb_count=396` | correctness (fails closed) | every carrier-path caller passes the SPS count; a wrong value finds no IDR, so no carriers, never wrong ones |
| `bitstream_ops.reconstruct_video`, `analysis_cache._build_reconstruction_context` | `mb_count_per_slice`, fallback `264` without an SPS | correctness | SPS count; the fallback is unreachable (the GOP policy requires an SPS before the first slice) |
| `bitstream_ops._calculate_nC(pic_width_in_mbs=22)` | width | none | dead code (no callers); nC is computed within the macroblock |
| `blind_sync_streaming`, `blind_sync_adaptive` globalisation; E2E RBSP tamper check | MBs per slot | correctness | SPS count, one slot per coded slice |
| `core/chaos.ChaosTransformer.shuffle_positions` | `396`, `22`, bottom row `14` | ordering/quality | original contracts (pinned); groups 396-MB "frames" (quarter pictures at 4CIF, straddling pictures at HD) and prefers stripes of 88 MBs in mid-picture |
| `core/stego.sort_blocks_interleaved` (`stego.py`, `parallel_analysis.py`) | `_CIF_MB_COUNT`, `_CIF_MB_WIDTH` | ordering/quality | pre-shuffle order of the sign-bit (`t1`) and full analyses; pinned for the original contracts, ignored by the `*-geo` contracts (canonical order first) |
| `blind_sync._cap_per_idr`, `_filter_bottom_zone`, `derive_blind_positions_*` | `cif_mb_count=396`, `cif_mb_width=22` | ordering/quality | used only by contracts with `max_bits_per_idr` / `bottom_rows` > 0 (header/diagnostic contracts, none of the lattice ones); the `*-geo` contracts pass the SPS geometry |
| `core/matrix_embedding.rank_positions_cost_guided`, `embedder.py` chaos shuffle, `core/pipeline*` | `396` | ordering/quality | legacy SEC1 CIF pipeline only, not on the lattice path |
| `bitstream_ops.batch_psnr_validate` | "4 bottom rows" | quality | uses the SPS width already; row count tuned on CIF (legacy pipeline) |
| `benchmark/_common.py`, `sec1_quality.py`, `sec2_capacity.py`, `sec3_methods.py`, `blind_sync_diagnostic.py`, `validated_pool_proxy_diagnostic.py`, `latticezk_adaptive_e2e.py`, `latticezk_adaptive_sim.py` | `396` / `22` | benchmark-only | CIF benchmarks (case names are CIF) |
| `latticezk_ml_steganalysis.py`, `latticezk_embedding_sim.py` | `--macroblocks-per-frame` default `396` | benchmark-only | the Q2 sweep passes the case's `macroblocks_per_frame` (3 600 / 8 160 in the HD cases) |

**Fix.** The original contracts keep the CIF-grid order: their carrier
profile ids, positions hashes, canonical digests and stego bytes are pinned
(recorded with commit `c027c87` before the change) by
`src/runtest/test_geometry_aware_ordering.py` on a CIF cut of a checked-in
fixture and a synthetic 4CIF clip, and were also checked on a 10-frame
foreman CIF cut and a 4-frame city 4CIF cut
(`benchmark/results/q2/hd_order_compat.json`). Three new contracts select the
SPS-geometry order through a `carrier_order` field (so `dataclasses.asdict`,
the carrier profile id, policy hash, relation and public sync key all differ):

| E2E `--carrier` | contract version | carriers as |
|---|---|---|
| `magnitude-geo` | `stable-carriers-sps-geometry-v1` | `magnitude` |
| `t1-geo` | `t1-sign-sps-geometry-v1` | `t1` |
| `adaptive-geo` | `adaptive-stc-magnitude-sps-geometry-v1` | `adaptive` (STC coded) |

`src/core/carrier_order.py` (`sps-geometry-low-drift-v1`): canonical
`(mb, block, coefficient)` order; group by slot `mb // (W x H)` from the SPS
(one slot per coded slice); within a slot the last `round(2/9 x rows)` rows of
the slot's carrier extent first (4 of 18 at CIF, 8 at 4CIF, 10 at 720p, 15 at
1080p; per slice for multi-slice pictures, since intra prediction does not
cross slices), each group in SHA-256-keyed order; slots round-robin. The
`max_bits_per_idr` / `bottom_rows` filters use the SPS grid too. The order
depends only on the (embedding-invariant) carrier set, the SPS and the key, so
the extractor recomputes it from the stego.

## Measurements (CIF, QP 22, magnitude carriers)

`python -m benchmark.latticezk_gop_eval --cases benchmark/latticezk_gop_cases.json
--data-root <tree with data/raw>`; results in `benchmark/results/q2/gop_*.json`
and `gop_summary.json`. Encoding (in `latticezk_gop_eval.encode_command`):

```text
ffmpeg -i data/raw/<clip>.y4m -frames:v N -c:v libx264 -profile:v baseline -coder 0 -bf 0 \
       -g G -keyint_min G -sc_threshold 0 -qp 22 -threads 4 -f h264 <clip>_gG.h264
```

The end-to-end run uses the **TOY** parameter set (registered, 413-byte
envelope) because the 8 165-byte BDLOP_OPEN_128 envelope (7 589 B with v1) does not fit a
200-300-frame GOP > 1 CIF clip (see "frames needed"); the transport, digest and
statement code paths are the same. Quality is luma PSNR of the decoded stego
against the decoded cover, all frames including P frames. Each row is one run
with a random sync key, so the carriers (and PSNR) differ between runs: an
earlier container GOP 8 run gave 46.80 / 43.96 / 38.67 dB.

| clip (frames) | GOP | seg. | carrier bits /100 fr | bits /IDR | 128-bit reg. needs (frames) | carriers used / IDRs touched | frames changed | PSNR all | PSNR changed | worst frame |
|---|---|---|---|---|---|---|---|---|---|---|
| container (200) | 1 | 100 | 50 757 | 508 | 120 | 3 600 / 100 | 100 | 63.71 | 60.70 | 55.58 |
| container (200) | 8 | 104 | 6 376 | 510 | 953 | 3 600 / 13 | 104 | 47.02 | 44.18 | 40.91 |
| container (200) | 25 | 100 | 2 030 | 507 | 2 992 | 3 896 / 8 | 200 | 39.25 | 39.25 | 32.02 |
| foreman (300) | 1 | 100 | 14 178 | 142 | 429 | 3 600 / 100 | 100 | 58.87 | 54.09 | 42.39 |
| foreman (300) | 8 | 152 | 1 793 | 142 | 3 387 | 3 896 / 38 | 300 | 53.21 | 53.21 | 44.57 |
| foreman (300) | 25 | 100 | 522 | 131 | 11 631 | does not fit (TOY needs 16 segments of 27 B) | – | – | – | – |

All runs verified blind; replay, a random one-bit tamper and a one-bit flip
inside a P slice of a carrier segment were rejected (reason: statement
mismatch, i.e. the digest, not a parse failure); every P slice was
byte-identical (175/175, 192/192, 262/262). Embedding / verification took
8-14 s / 4.7-6.3 s for GOP > 1 against 16-46 s / 13-42 s all-intra (only IDR
slices are parsed).

**Capacity.** An IDR picture carries what an all-intra frame of the same
content carries (508 vs 510 bits for container), and P slices carry nothing,
so capacity per frame falls by the GOP length. The registered 128-bit
envelope needs ~1 000 frames (40 s at 25 fps) for container at GOP 8, ~3 000
(2 min) at GOP 25; low-texture foreman needs 3 400 and 11 600 frames.

**Drift.** P slices are untouched but predict from the modified IDR, so every
frame of a GOP whose IDR changed differs from the cover (`frames changed` =
GOP x IDRs touched). Within a GOP the error neither grows nor decays much:
container loses 0.04 dB over 7 P frames at GOP 8 and 0.09 dB over 24 at GOP
25 (`luma_psnr_by_gop_position_in_modified_gops_db`); foreman, with motion,
recovers 0.6 dB by the end of the GOP. The worst frame is an IDR or a late P
frame of a dense GOP.

**Quality cost vs all-intra.** It comes from density, not from drift
accumulation: the same envelope is packed into GOP-times fewer pictures
(container: 36 carriers per IDR at GOP 1, 277 at GOP 8, 487 at GOP 25), and
each modified picture's distortion is then copied into GOP-1 P frames. For the
same envelope, container's PSNR on changed frames drops from 60.7 dB to 44.2
and 39.3 dB, the worst frame from 55.6 to 40.9 (38.7 in the other run) and
32.0 dB. Foreman, whose
IDRs are carrier-poor, stays at 53-54 dB because its per-IDR change count is
small either way.

## HD readiness

Tested here on synthetic encodes only (`test_gop_and_hd_support.py`): 1280x720
with four slices per picture (parse, one slot per slice, carriers in every
slice, two one-frame segments with disjoint global positions, extraction and
carrier recomputation equal) and 1920x1080 (SPS 120 x 68, cropped decode
1920x1080, embed/extract and recomputation equal).

**Memory and time** (`benchmark/latticezk_hd_profile.py`, serial analysis,
one segment = the cut; analysis + embedding + extraction; results in
`benchmark/results/q2/hd_profile_*.json`):

| cut | MBs/picture | coded luma blocks/frame | peak MB/frame | s/frame (3 passes) |
|---|---|---|---|---|
| city 4CIF (natural) | 1 584 | 24 200 | 35.5 | 10.2 |
| container upscaled to 720p | 3 600 | 38 000 | 69.3 | 8.5 |
| container upscaled to 1080p | 8 160 | 70 400 | 117 (analysis) | 24.1 |
| testsrc2 + noise, 1080p (every block coded) | 8 160 | 130 000 | 199 | 41.3 |

Memory is 1.2-1.6 KB per coded luma block (offsets, coefficients, nC, lengths
kept per block) plus ~50 MB. Scaling natural 4CIF content per macroblock gives
**~80 MB per 720p frame and ~180 MB per 1080p frame** (upper bound ~90 / ~200
MB) of segment, and ~7.7 / ~17.6 s per frame per pass (serial). The peak
depends on `frames_per_segment` only (one segment is analysed at a time), so
the HD cases use 25-frame (720p) and 10-frame (1080p) segments: ~2.1 GB and
~1.9 GB peak. With GOP > 1 only IDR pictures count (a 200-frame GOP 8 segment
at 720p holds 25 IDRs, ~2.1 GB). Natural HD capacity is not measured; scaling
4CIF city (~1 000 bits per frame at QP 22) suggests ~2 300 (720p) and ~5 200
(1080p) bits per frame, so a registered 128-bit envelope needs 2-3 segments.

### Measured on natural HD cuts (stream C4, partial)

10-frame cuts, libx264 Baseline all-intra QP 22 (`-g 1 -keyint_min 1
-sc_threshold 0 -coder 0 -bf 0`), `frames_per_segment` 5, magnitude carriers,
`ZKSTEGO_ANALYSIS_WORKERS=2`, run next to another memory-heavy job. Results in
`benchmark/results/q2/hd_order_*.json` (`benchmark/latticezk_hd_order.py`).
The RAM watchdog (available < 1.2 GB, caused by the other job) interrupted
three of the runs; their files say `"complete": false`, and the benchmarks were
then deferred.

| cut | carrier bits / picture | v2 registered envelope (8 165 B) needs |
|---|---|---|
| park_joy 720p | 4 668-6 157 (mean 5 455) | 13 pictures (fill 1.0), 14 (0.9), 25 (0.5) |
| park_joy 720p, 4 slices | 4 666-6 178 (mean 5 474) | same |
| riverbed 1080p | 147-205 (mean 171) | ~400 pictures; the whole 250-frame clip holds < 43 kbit, so it **does not fit** with magnitude carriers |

So the v2 envelope does not fit any 10-frame HD cut; the end-to-end run used
the registered **TOY** set (413 B): park_joy 720p, adaptive chunks, one
segment carried 3 584 carriers; `magnitude-geo` verified blind, replay and a
one-bit tamper were rejected (embed 61 s, verify 52 s, peak process-tree RSS
477 MB); the original `magnitude` order on the same cut also verified (37 s /
28 s, 448 MB; random sync keys differ between the two runs).

PSNR of the changed frames / worst frame (dB), original CIF-grid order ->
SPS-geometry order, same payload, key and chunk layout per pair:

| cut, fill | original | geometry |
|---|---|---|
| park_joy 720p, 0.25 (key 0 / key 1) | 42.68 / 37.25, 44.09 / 39.67 | 41.69 / 37.42, 44.14 / 38.67 |
| park_joy 720p, 0.5 | 37.98 / 33.37 | 40.67 / 34.93 |
| park_joy 720p, 0.9 | 36.84 / 33.84 | 36.40 / 30.90 |
| park_joy 720p 4 slices, 0.25 | 43.84 / 39.77 | 45.72 / 41.60 |
| park_joy 720p 4 slices, 0.5 | 40.00 / 36.29 | 40.96 / 34.88 |
| riverbed 1080p, 0.5 | 49.37 / 47.09 | 51.75 / 49.44 |
| E2E TOY (12 % of segment 0, different keys) | 48.38 / 46.49 | 46.80 / 42.95 |

Over the seven paired runs the geometry order gains +0.9 dB on the changed
frames on average (range -1.0 to +2.7) and +0.1 dB on the worst frame (range
-2.9 to +2.4): no consistent quality gain at this sample size. Concentrating
the first carriers in the bottom 22 % of each picture shortens the drift path
but raises the local change density, and the two effects roughly cancel. The
geometry contracts are therefore a correctness/consistency fix of the order
(real pictures, real bottom rows, slice-relative zones), not a demonstrated
quality improvement. Peak memory: ~690 MB for 5-frame 720p segments
(analysis + embed + extraction), ~955 MB for 5-frame 1080p segments; ~10 s
per 720p frame per embed (two analysis passes, reconstruction, decode check)
under contention.

**Not measured** (deferred): the multi-key repetition (5 of 12 runs done),
multi-slice and 1080p fill 0.9 with extraction, old_town_cross and pedestrian
capacity, trailing-one (`t1-geo`) capacity at HD, any v2 (8 165 B) HD end-to-end
run, and `latticezk_hd_profile` on the natural cuts.

## Limits

* Carriers come only from IDR slices; non-IDR I slices and P slices carry
  nothing (P-slice residual carriers would need motion-compensated drift
  control and inter CAVLC patching, not attempted).
* GOP > 1 needs a fixed GOP whose length divides `frames_per_segment`
  (encode with `-keyint_min G -sc_threshold 0`, closed GOPs, no B frames);
  open-GOP recovery points, B slices, FMO/ASO and redundant pictures are
  refused.
* Drift reaches every frame of a touched GOP. The operating-envelope quality
  guard (every modified frame >= 40 dB) holds for foreman at GOP 8 (worst
  44.6 dB), is borderline for container at GOP 8 (40.9 / 38.7 dB in two runs)
  and fails at GOP 25 (32.0 dB), even with the 413-byte envelope; spreading the envelope over more GOPs (smaller
  chunks, longer clips) is the lever, as for all-intra.
* HD memory grows with `frames_per_segment x MBs per picture` (the analysis
  keeps every coded block's offsets); pick short segments at 1080p.
* The original contracts' order heuristics assume a CIF grid (order only,
  pinned); the `*-geo` contracts use the SPS grid, with no consistent PSNR gain
  measured so far.
* Magnitude carriers are thin on smooth 1080p content (riverbed: ~171 bits per
  picture), too few for the 128-bit envelope in the whole clip; such clips need
  the trailing-one carriers, whose HD capacity is not measured.
* The 128-bit envelope was not run end to end on GOP > 1 or HD here (machine
  constraints); the commands are below.

## Integrator runs

No 720p/1080p source is in `data/raw`, and none is in `scripts/data_manifest.json`.
The Xiph derf sequences used (sizes checked with `curl -I`, 2026-10-21; add
their SHA-256 to the manifest after download):

```sh
cd VideoLevel
curl -L -o data/raw/park_joy_420_720p50.y4m       https://media.xiph.org/video/derf/y4m/park_joy_420_720p50.y4m        # 691 MB, 500 frames
curl -L -o data/raw/old_town_cross_420_720p50.y4m https://media.xiph.org/video/derf/y4m/old_town_cross_420_720p50.y4m  # 691 MB, 500 frames
curl -L -o data/raw/pedestrian_area_1080p25.y4m   https://media.xiph.org/video/derf/y4m/pedestrian_area_1080p25.y4m    # 1.17 GB, 375 frames
curl -L -o data/raw/riverbed_1080p25.y4m          https://media.xiph.org/video/derf/y4m/riverbed_1080p25.y4m           # 778 MB, 250 frames
sha256sum data/raw/*_720p50.y4m data/raw/*_1080p25.y4m
```

1. HD sweep (encode, capacity scan, registered BDLOP_OPEN_128 E2E with
   replay/tamper checks, classical steganalysis), one case at a time:

   ```sh
   ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_q2_sweep \
       --cases benchmark/latticezk_hd_cases.json --workers 1 --work tmp/hd_sweep
   ```

   The cases use `magnitude-geo` (720p) / `t1-geo` (1080p) with capacity-adaptive
   chunks (no capacity scan; the greedy plan stops at the segment that
   completes the envelope, so only those segments are analysed) and short
   segments (10 frames at 720p, 5 at 1080p, 80 = 10 IDRs for the GOP 8 case).
   Estimate from the measurements above: peak ~1.1 GB per process at 720p
   (10-frame segments) and ~1 GB at 1080p (5-frame segments), plus ffmpeg.
   park_joy 720p needs ~14 pictures (2 segments): ~10-15 min with the
   security checks; old_town_cross 720p is unmeasured (budget 30-60 min);
   the GOP 8 park_joy case ~2 segments of 10 IDRs, ~20-30 min. The 1080p
   `t1-geo` cases are the uncertain part: sign-bit analysis cost ~17 s per
   4CIF frame and pass, i.e. ~90 s per 1080p frame and pass, and their capacity
   is unknown; measure it first and drop or resize those cases if it is low:
   `ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_capacity_scan data/encoded/riverbed_1080p_q22_g1_100f.h264 --carrier t1-geo --frames-per-segment 2 --segments 1`.
   Ordering comparison on a cut:
   `python -m benchmark.latticezk_hd_order --video <cut> --frames-per-segment 5 --fill 0.25 0.5 --keys 3 --output benchmark/results/q2/hd_order_<name>.json`.
2. 128-bit envelope at GOP > 1 (CIF, looped sources; IDR-only analysis, peak
   < 1 GB):

   ```sh
   ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_gop_eval \
       --cases benchmark/latticezk_gop_cases.json \
       --only container_g8_3000f_reg128 coastguard_g8_3000f_reg128 container_g25_6000f_reg128
   ```

   Expected: container GOP 8 needs ~7 segments of 200 frames (1 400 frames),
   coastguard GOP 8 ~8 (1 600), container GOP 25 ~17 (3 400); 10-30 min each.
3. The CIF short cases are reproduced by the same command without `--only`.
