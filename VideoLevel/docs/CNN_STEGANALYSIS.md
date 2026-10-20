# CNN steganalysis of lattice-ZK stego video (roadmap A6)

This study adds a deep-learning detector, a spatial-domain CNN trained on the GPU,
next to the feature-based FLD ensembles in `benchmark/latticezk_ml_steganalysis.py`
(results in `benchmark/results/q2/ml_eval.json` and `carrier_compare.md`).
Code: `benchmark/latticezk_cnn_steganalysis.py`. Test:
`src/runtest/test_latticezk_cnn_steganalysis.py`. Raw results:
`benchmark/results/q2/cnn_*.json`.

## Summary

| Carrier (equal payload) | Protocol | CNN P_E (crop-mean) | CNN AUC | CNN P_E (full-frame) | Best FLD P_E, same protocol |
|---|---|---|---|---|---|
| magnitude LSB, 5 clips | leave-one-clip-out | **0.466** | 0.529 | 0.466 | 0.399 (coefficient), 0.458 (pixel) |
| magnitude LSB, 5 clips | paired half split | **0.474 / 0.464** | 0.528 / 0.549 | 0.477 / 0.468 | 0.357 (combined), 0.410 (pixel) |
| T1 sign, spread, 4 clips | leave-one-clip-out | **0.273 / 0.278** | 0.766 / 0.754 | 0.194 / 0.212 | 0.401 (combined), 0.404 (pixel) |
| T1 sign, spread, 4 clips | paired half split | **0.168 / 0.142** | 0.906 / 0.932 | 0.116 / 0.105 | 0.317 (combined), 0.344 (pixel) |

`a / b` = seed 20261021 / seed 20261022 (independent initialisation and splits).
P_E = min over thresholds of (P_FA + P_MD) / 2; 0.5 is chance.

* **Magnitude carrier (the default):** the CNN stays at chance (P_E 0.46–0.47,
  AUC 0.53–0.55). It does worse than the coefficient-domain FLD (0.399 LOCO),
  which remains the strongest detector we have for this carrier. Neither detector
  gets below P_E 0.35 on single frames.
* **T1-sign carrier, same payload and frames:** the CNN finds it. Frame P_E is
  0.27 leave-one-clip-out (0.19–0.21 with the full-frame logit) and 0.14–0.17 on
  the paired split. Per clip, container (0.09) and coastguard (0.19) are clearly
  detected, while city and hall stay near 0.40. This is much stronger than the
  FLD ensembles (0.40 LOCO). The CNN shows that pixel-domain steganalysis can see
  the T1-sign carrier, which the hand-made features missed.
* **Margin:** doubling the magnitude-carrier change (`--amplify 2`, a synthetic
  proxy) already gives P_E 0.18 when the CNN is trained on it. The default carrier
  is therefore not far below the CNN's detection threshold.

## Data

| Set | Cases (`tmp/q2/<case>.h264`) | Cover (`data/encoded`) | Modified frame pairs |
|---|---|---|---|
| magnitude | container/coastguard/city/hall `_cif_q22_reg`, `deadline_cif_q22_reg` | `*_cif_q22_g1.h264`, `deadline_cif_q22_g1_1000f.h264` | 200 + 200 + 300 + 300 + 700 = 1700 |
| t1_spread | container/coastguard/city/hall `_cif_q22_reg_t1_spread` | same covers | 200 + 200 + 300 + 300 = 1000 |

* Each case carries the same 7589-byte envelope in the same segments (2 or 3
  segments of 100 frames). The magnitude and T1-spread sets therefore have equal
  payload and equal density, and differ only in the carrier. All streams are
  CIF 352x288, all-intra (GOP 1), QP 22.
* Cover and stego are decoded with `decode_luma_native`, which gives the exact Y
  plane through raw yuv420p. A frame is kept when its stego luma differs from its
  cover luma in at least one pixel. The counts match `frame_quality.frames_modified`
  for every case except deadline: 700 frames differ in pixels, while the report
  counts 684. Pairs are cached as uint8 in `tmp/cnn_cache/cnn_pairs_<case>.npz`
  (gitignored; about 545 MB on disk, about 340 MB in RAM for the magnitude set).
* The pixel change is spread out but small. For the magnitude set, 48–79 % of
  pixels change (intra prediction carries each coefficient change into later
  blocks), mean |Δ| ≈ 2, MSE 1.8–6.8. For T1-spread, 12–17 % of pixels change,
  MSE 0.9–2.5.
* The FLD reference numbers (`ml_eval.json`, `carrier_compare.md`, recomputed
  for this study with `latticezk_ml_steganalysis evaluate` and reproduced exactly)
  use 1300 magnitude pairs, because the deadline features cover only 3 segments.
  The CNN uses all 700 deadline frames.

## Method

**Network.** A Yedroudj-Net-style detector (163 k trainable parameters):

1. A fixed front end of the 30 SRM high-pass filters (1st, 2nd and 3rd order,
   SQUARE 3x3/5x5, EDGE 3x3/5x5). They are applied in fp32 to (pixel − 128)
   with integer taps and then divided by their normaliser, so the residuals are
   exact and unaffected by TF32 or fp16. The output is truncated with TLU(3).
2. conv5x5(30), then ABS, BN, TLU(3); conv5x5(30), then BN, TLU(2), avgpool/2.
3. Two stages of conv3x3 (32, 64), each followed by BN, ReLU and avgpool/2.
   Then conv3x3(128), BN, ReLU and global average pooling.
4. FC 128→128, ReLU, dropout 0.3, FC→1 logit, trained with BCE.

**Training** (fixed for every run; CLI defaults):

| Setting | Value |
|---|---|
| Crop | random 256x256, offsets on the 4-pixel H.264 transform grid |
| Augmentation | one random D4 transform (flip/rot90) per pair |
| Mini-batch | 16 cover/stego pairs (32 images); each cover and its stego share the crop and transform |
| Optimiser | AdamW, lr 2e-4, weight decay 1e-4, cosine schedule, fp16 autocast after the SRM layer |
| Epochs | at most 40, one crop per training pair per epoch |
| Payload curriculum | epochs 0–14 train on round(cover + α·(stego − cover)), α going linearly from 6 to 1; from epoch 15 on, α = 1 (the real stego) |
| Early stopping | lowest validation P_E (ties broken by validation loss), patience 10, only α = 1 epochs can be selected |
| Validation | taken from the training clips only: the last 20 % of each training clip's frames (LOCO), or a random 20 % of the training pairs (paired split) |

The curriculum was needed. Trained from scratch at α = 1, the loss stayed at
ln 2 for 15+ epochs on every set. With α = 8 the network learns the change at
once (test P_E 0.00–0.07 at α = 8), and decaying α moves those weights to the
real signal. Amplified pixels are rounded to integers, so fractional values
cannot serve as a shortcut.

**Scoring.**

* Frame score: the mean logit over a 3x3 grid of 256x256 crops covering the
  full frame (offsets {0, 16, 32} x {0, 48, 96}). The single full-frame logit is
  also reported. Model selection used full-frame validation logits, and for T1
  the full-frame score is the better of the two.
* Video score: the mean frame score over a video's modified frames, computed per
  clip (one cover and one stego video per clip) and per 100-frame segment (34
  magnitude units, 20 T1 units).

**Protocols.**

* (a, b) Leave-one-clip-out: train on the other clips and test on every
  modified frame of the held-out clip.
* (c) Paired half split: in each clip, a random half of the pairs is the test
  set and the rest is training plus validation.

Cover/stego pairs always stay on the same side of a split. The attacker is
strong: it has exact pairs from the same encoder and knows which frames carry bits.

## Results

### Per-fold, leave-one-clip-out (seed 20261021)

| Held-out clip | Magnitude P_E / AUC | Magnitude FLD coeff / pixel P_E | T1-spread P_E / AUC | T1-spread full-frame P_E | T1-spread FLD combined / pixel P_E |
|---|---|---|---|---|---|
| city | 0.487 / 0.503 | 0.383 / 0.488 | 0.403 / 0.600 | 0.352 | 0.457 / 0.443 |
| coastguard | 0.470 / 0.515 | 0.340 / 0.473 | 0.193 / 0.873 | 0.130 | 0.398 / 0.390 |
| container | 0.448 / 0.549 | 0.385 / 0.448 | 0.090 / 0.971 | 0.033 | 0.343 / 0.358 |
| deadline | 0.490 / 0.508 | 0.452 / 0.465 | n/a | n/a | n/a |
| hall | 0.437 / 0.569 | 0.435 / 0.417 | 0.405 / 0.621 | 0.262 | 0.407 / 0.425 |
| **mean** | **0.466 / 0.529** | 0.399 / 0.458 | **0.273 / 0.766** | **0.194** | 0.401 / 0.404 |

T1-spread LOCO with seed 20261022 gives per-fold P_E 0.398 / 0.193 / 0.085 / 0.435
(mean 0.278, AUC 0.754, full-frame P_E 0.212). The per-clip pattern repeats.

### Paired half split, per clip (P_E; seed 1 / seed 2)

| Clip | Magnitude | T1-spread |
|---|---|---|
| city | 0.470 / 0.467 | 0.217 / 0.193 |
| coastguard | 0.455 / 0.450 | 0.010 / 0.000 |
| container | 0.460 / 0.430 | 0.075 / 0.065 |
| deadline | 0.481 / 0.473 | n/a |
| hall | 0.420 / 0.387 | 0.190 / 0.200 |
| all clips | 0.474 / 0.464 | 0.168 / 0.142 |

### Video-level decision

| Set / protocol | Stego video scores above its cover | Clip videos, pooled P_E / AUC | 100-frame segments, pooled P_E / AUC | Segment AUC within each fold |
|---|---|---|---|---|
| magnitude LOCO | 5/5 | 0.40 / 0.60 | 0.41 / 0.54 | 0.56, 0.75, 0.75, 0.57, 0.78 |
| magnitude paired (s1 / s2) | 5/5, 5/5 | 0.30 / 0.64, 0.20 / 0.76 | 0.41 / 0.58, 0.35 / 0.65 | n/a |
| T1-spread LOCO (s1 / s2) | 4/4, 4/4 | 0.375 / 0.625, 0.25 / 0.75 | 0.40 / 0.59, 0.25 / 0.70 | 0.78, 1, 1, 0.78 / 0.67, 1, 1, 1 |
| T1-spread paired (s1 / s2) | 4/4, 4/4 | 0.00 / 1.00, 0.00 / 1.00 | 0.00 / 1.00, 0.00 / 1.00 | n/a |

How to read this table:

* "Stego above its cover" is a paired comparison: it needs the cover, which a
  real warden does not have. For the magnitude carrier the stego video is always
  scored higher, but by only 0.001–0.06 logits. The spread between clips is far
  larger (mean scores range from −0.3 to +8.7 across LOCO folds), so this does not
  turn into a decision a warden could use.
* Pooling LOCO videos across folds mixes uncalibrated models. Each fold's offset
  dominates, which is why LOCO pooled video P_E stays at 0.25–0.41 even for T1.
  Within a fold, i.e. with one model and one unseen clip, T1 segments separate
  perfectly for coastguard and container.
* With the paired split (same model, seen scenes), every T1 clip and every T1
  segment is classified correctly. Magnitude segments are not (P_E 0.35–0.41).

### Detectability margin (synthetic amplification)

* `--amplify 2` trains, validates and tests on round(cover + 2·(stego − cover)),
  paired split:
  * magnitude: P_E 0.183, AUC 0.904. Hall 0.000, container 0.075, deadline 0.194,
    city 0.257, coastguard 0.240. Video and segment pooled P_E 0.00.
  * T1-spread: P_E 0.001, AUC 0.9999.
* The α = 1 LOCO magnitude models, scored on amplified test frames without
  retraining, give mean P_E 0.27 at α = 2 and 0.18 at α = 4 (container 0.15/0.03,
  hall 0.00/0.00).
* Amplification is a pixel-domain proxy. It is not a re-encoded stream with a
  denser payload, so it only shows that the change is not far below the
  detector's reach.

## Interpretation

1. For the magnitude-LSB carrier that the pipeline uses by default, a GPU CNN
   does not improve on the FLD study. Its frame-level P_E of 0.46–0.47 is inside
   the FLD range of 0.39–0.47 and worse than the coefficient-domain FLD. The
   change is small (≈ 2 levels), low-frequency and spread by intra prediction,
   so it looks like ordinary content in the decoded frame. A detector working in
   the coefficient domain stays the better tool against this carrier, and is the
   one a stronger study should improve (for example, a CNN on the 4x4
   coefficient planes).
2. The T1-sign carrier is clearly weaker against learned pixel steganalysis.
   Equal payload, equal frames and a smaller pixel MSE still give frame P_E 0.27
   on unseen clips and 0.14–0.17 on seen clips, with perfect segment decisions
   on the paired split. A sign flip of a trailing ±1 is a 2-level step at a
   high-frequency position, the kind of local high-frequency residual that SRM
   filters pick up. The feature-based study (pixel FLD 0.40) underestimated this
   by a wide margin. This supports keeping magnitude as the default carrier and
   treating T1 as a capacity mode that is not steganographically secure.
3. Detectability depends on the clip. Static, textured scenes (container,
   coastguard) are the easiest for T1, while city and hall resist. The magnitude
   margin experiment points the other way: hall is the first clip to become
   detectable when the change grows.

## Caveats

* The datasets are small (1000–1700 frame pairs from 4–5 clips, with strongly
  correlated neighbouring frames), and the network is small, trained for at most
  40 epochs. A larger SRNet-class model, more clips, or a pretrained
  (e.g. BOSSbase/ALASKA) initialisation could push P_E lower. Read these numbers
  as an upper bound on P_E for a strong-but-bounded attacker, not as a
  security proof.
* Only two seeds were run: LOCO magnitude has one seed, and all other main
  protocols have two. The seeds agree within about 0.03 P_E. No confidence
  intervals are given. In LOCO, each fold is one clip.
* Hyper-parameters (lr, curriculum length) were chosen in a short exploration on
  the magnitude paired split. The paired-split numbers therefore carry a small
  selection bias. LOCO was not used for tuning.
* The paired split shares scenes between training and test (as in the FLD
  protocol). Only LOCO measures generalisation to unseen content.
* "Modified" frames are those with any luma pixel difference. On deadline this
  includes 16 frames that the e2e report does not count as modified.
* Video-level results pool few units (8–10 clip videos, 20–34 segments), so the
  0.00 rates mean "no errors among these units", not a measured error rate.

## Reproduce

Data paths default to `VideoLevel/{data/encoded,tmp/q2,benchmark/results/q2}`.
Override them with `--encoded-dir/--stego-dir/--reports-dir` when the data
lives in another checkout.

```bash
python -m benchmark.latticezk_cnn_steganalysis dataset --set magnitude
python -m benchmark.latticezk_cnn_steganalysis dataset --set t1_spread
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol loco \
    --output benchmark/results/q2/cnn_magnitude_loco.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol loco \
    --output benchmark/results/q2/cnn_t1_spread_loco.json
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol paired \
    --output benchmark/results/q2/cnn_magnitude_paired.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol paired \
    --output benchmark/results/q2/cnn_t1_spread_paired.json
# margin experiment / replication
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol paired \
    --amplify 2 --output benchmark/results/q2/cnn_magnitude_paired_margin_a2.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol loco \
    --seed 20261022 --output benchmark/results/q2/cnn_t1_spread_loco_seed2.json
python -m pytest src/runtest/test_latticezk_cnn_steganalysis.py -q
```

Environment: Python 3.12.10, torch 2.11.0+cu128 (CUDA 12.8, cuDNN 9.19),
NVIDIA RTX 3060 Laptop GPU (6 GB; peak about 4.3 GB used). The whole dataset sits
on the GPU as uint8. The peak host working set while training on the magnitude
set is about 2.0 GB, measured with psutil; most of it is the CUDA/torch runtime.

Wall-clock times:

| Run | Time |
|---|---|
| Magnitude LOCO (5 folds) | 27.8 min |
| T1-spread LOCO (4 folds) | 13.2 min |
| Magnitude paired | 3.6–4.3 min |
| T1-spread paired | 2.6–2.9 min |
| Dataset decode (both sets) | about 1 min |
