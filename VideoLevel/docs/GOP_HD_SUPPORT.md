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
  `test_non_cif_carrier_capacity.py`). The embedding-order heuristics
  (`sort_blocks_interleaved`, the chaos shuffle's bottom-row preference) still
  assume a CIF MB width of 22; at HD they only change the deterministic order,
  identically at embedding and extraction, not correctness.

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
* The embedding-order heuristics assume a CIF macroblock width (order only).
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

   Estimate (serial pass costs above; two workers speed up analysis only):
   each 720p case ~45 min, each 1080p case ~40 min, the 720p GOP 8 case ~40
   min; ~3.5 h in total; peak ~2.1 GB per process (plus ffmpeg). Optional
   check of the estimate on a real cut first:
   `python -m benchmark.latticezk_hd_profile --video data/encoded/park_joy_720p_q22_g1_200f.h264 --frames 3 6 --extrapolate 25 50`.
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
