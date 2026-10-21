# Cost-adaptive carriers (roadmap B1)

Status: implemented behind a new carrier contract,
`AdaptiveOperatingContract` (`version = "adaptive-stc-magnitude-video-only-v1"`,
`src/blind_sync.py`), with the code and cost model in
`src/core/adaptive_carriers.py`.  The existing contracts are unchanged: their
`dataclasses.asdict` serialisation, carrier profile ids and stego output bytes
are identical to commit `18c5123` (pinned by tests).

## What changes and what does not

The **carrier set is the same** as the stable magnitude contract
(`stable-carriers-video-only-v1`): in every patchable luma 4x4 block, the first
re-derivable AC coefficient with `|level| >= 4` that is not a trailing one; its
`|level|` LSB is the carrier bit.  The set, and its order under the keyed
chaos shuffle, depends only on `|level| >> 1`, the zero pattern and the CAVLC
patchability checks, none of which an LSB change alters, so the extractor
recomputes it from the stego video exactly as before.

What changes is the **mapping from envelope bits to carrier bits**:

| | direct (current) | adaptive (B1) |
|---|---|---|
| carriers per segment | one per envelope bit (prefix of the keyed order) | **all** stable carriers of the segment |
| carrier bit | = envelope bit | free; the envelope is the *syndrome* `H y` |
| changes | about one per two bits, at random carriers | Viterbi minimum-cost solution of `H y = m` |
| extractor needs | key, contract | key, contract (code parameters are in it) |

The proof/statement layer is untouched.  The statement binds
`carrier_count`, `positions_hash` and the carrier-normalised video digest; for
the adaptive contract these cover every carrier of the code, which are fixed
before the proof exists (a same-length placeholder fixes `m`, the invariant
carrier set fixes `n`).  The contract's extra fields change the carrier profile
id, so an adaptive video can only verify under a registry entry made for the
adaptive profile.

## Coding: syndrome-trellis codes

Per 100-frame segment the envelope (14-byte header + body) is coded in two
independent STCs (Filler, Judas, Fridrich, *Minimizing additive distortion in
steganography using syndrome-trellis codes*, IEEE TIFS 2011):

* **header**: the first `header_carriers_per_bit x 112` carriers in keyed
  order carry the 112 header bits (default 1, i.e. 112 carriers at rate 1, so
  the contract needs no more carriers than direct embedding; the header's
  ~56 changes are negligible next to the body's);
* **body**: all remaining `n_b` carriers carry the `m_b` body bits, rate
  `m_b / n_b`.  The extractor decodes the header, learns the envelope length
  from it, and therefore knows `m_b`; `n_b` is the invariant carrier count.

The parity-check matrix is the standard banded STC matrix built from a public
`h x w` submatrix (`h = stc_constraint_height = 10`, columns derived from
SHA-256 of a domain string, lowest and highest bit set so every message bit is
reachable); widths per message bit are `floor((j+1) n / m) - floor(j n / m)`.
Extraction is a single pass of XORs; embedding is a Viterbi search over
`2^h` states (numpy, about 1 s and 50 MB for 50 k carriers).  With uniform
costs it achieves 0.27 changes per bit at rate 0.6 (bound 0.25, direct 0.5).

Why this is compatible with a blind extractor and fixed envelopes, contrary to
the first expectation in the roadmap: the extractor never needs the costs or the
cover; it needs only `(n, m, h)`, all recomputable, and the keyed carrier order
it already derives.  "Wet" carriers are not needed because every stable
carrier is modifiable by construction.

## Cost model

`texture-magnitude-v1`, per carrier `i` in macroblock `M`:

```
rho_i = 1 / ( q_i * (1 + T_M / 32) )
q_i   = |level_i| >> 1                         (>= 2)
T_M   = sum over the 16 luma blocks of M, AC positions, of (|c| >> 1) + [c != 0]
```

* `q_i`: a +-1 change of a large level is relatively smaller, moves the
  per-position magnitude histogram less (counts are flatter there; bins above
  15 are merged in the detector) and gives a smaller pixel-domain residual
  relative to the content;
* `T_M`: changes hide better in textured macroblocks (the usual
  content-adaptivity argument of HUGO/WOW/UNIWARD), which is what the
  SRM-style pixel features see.

Every input is carrier-invariant, so the costs are recomputable from the stego
video (tested: identical cost vectors from cover and stego); the STC extractor
does not use them, but this keeps the door open for wet-paper or
threshold variants whose extractor must know the selection.

## Contract

```python
AdaptiveOperatingContract(            # src/blind_sync.py
    version="adaptive-stc-magnitude-video-only-v1",
    stable_carriers_only=True, require_bitstream_patchable=True,
    max_modifications_per_block=1, patchability_headroom=64,
    carrier_coding="stc", stc_constraint_height=10,
    header_carriers_per_bit=1,        # header code has rate 1: same capacity as direct
    cost_model="uniform",             # or "texture-magnitude-v1"
)
```

`benchmark/latticezk_video_e2e.py --carrier adaptive` (uniform costs) and
`--carrier adaptive-texture` (texture/magnitude costs) select it.  With
`header_carriers_per_bit=1` the contract fits exactly the segments the direct
magnitude contract fits (coastguard's first segment has 31 404 carriers for
30 696 envelope bits).  Unsupported settings (sign-bit carriers, more than one
carrier per block, per-IDR caps, bottom-zone filters, unknown coding or cost
model, height outside 1..12) are refused.

## Results

Setup: registered BDLOP envelope (7 589 B), `--chunk-bytes 3800`, two
100-frame segments per clip, all-intra CIF QP 22 cuts of the first 200 frames of
container, coastguard and deadline (city and hall do not fit the envelope in 200
frames with either contract).  Detectors and features are those of
`latticezk_ml_steganalysis` (attacker trains on exact cover/stego pairs from
the same encoder and knows which frames carry bits); 600 frame pairs per mode,
leave-one-clip-out (LOCO, 3 folds of 200 pairs) and a paired half split.

### Simulation used to choose the cost model


`benchmark/latticezk_adaptive_sim.py` (real stable carriers, coefficient
domain only, bitstream not rebuilt; `benchmark/results/q2/adaptive_sim.json`):

| Rule | Changes (container / coastguard / deadline) | LOCO FLD P_E (coefficient) |
|---|---|---|
| direct (current) | 30 503 / 30 575 / 30 542 | 0.394 |
| STC, uniform cost | 16 123 / 22 633 / 16 709 | **0.444** |
| STC, magnitude `1/q` | 18 194 / 23 310 / 18 530 | 0.426 |
| STC, texture `1/(1+T/32)` | 17 388 / 23 075 / 18 018 | 0.428 |
| STC, texture-magnitude-v1 | 19 005 / 23 787 / 19 322 | 0.423 |
| STC, `1/q^2`, `1/(q^2 (1+T/32))`, `1/k` | 21 344 / ... | 0.430, 0.433, 0.439 |

Every content cost bought its "better places" with 10-35 % more changes, and
against these detectors the change count dominated.  `uniform` is therefore
the default; `texture-magnitude-v1` stays available and was measured for real.

### Real E2E (`benchmark/results/q2/adaptive_e2e.json`)

All nine runs verified from the stego video alone (`verify_reason: ok`).

| Clip | Mode | Carriers | Changed coeffs | Changes / bit | PSNR (dB) | Worst frame (dB) | Embed / verify (s) |
|---|---|---|---|---|---|---|---|
| container | direct | 61 304 | 30 491 | 0.502 | 44.03 | 34.35 | 179 / 80 |
| container | STC uniform | 101 439 | **16 167** | 0.266 | **45.83** | 36.51 | 179 / 83 |
| container | STC texture | 101 439 | 19 125 | 0.315 | 45.85 | 35.65 | 187 / 80 |
| coastguard | direct | 61 304 | 30 673 | 0.505 | 41.85 | 32.65 | 227 / 104 |
| coastguard | STC uniform | 71 303 | **22 618** | 0.373 | **43.22** | 33.93 | 226 / 104 |
| coastguard | STC texture | 71 303 | 23 777 | 0.392 | 42.92 | 33.32 | 232 / 104 |
| deadline | direct | 61 304 | 30 531 | 0.503 | 39.43 | 28.74 | 184 / 84 |
| deadline | STC uniform | 95 332 | **16 750** | 0.276 | **41.82** | 32.48 | 231 / 101 |
| deadline | STC texture | 95 332 | 19 304 | 0.318 | 40.34 | 29.41 | 204 / 83 |

PSNR is the whole-video decoded average (all 200 frames are modified in every
run).  Learned steganalysis, P_E (higher is better for the embedder); the
"worst case" row is the minimum over the six detector/feature combinations:

| Protocol | Detector / features | direct | STC uniform | STC texture |
|---|---|---|---|---|
| LOCO | FLD, coefficient (340) | 0.406 | **0.431** | 0.404 |
| LOCO | FLD, pixel SRM-lite (500) | 0.412 | **0.450** | 0.443 |
| LOCO | FLD, combined | 0.407 | **0.438** | 0.428 |
| LOCO | worst case | 0.406 | **0.431** | 0.404 |
| paired split | FLD, coefficient | 0.352 | **0.392** | 0.393 |
| paired split | FLD, combined | 0.323 | **0.388** | 0.353 |
| paired split | worst case | 0.323 | **0.388** | 0.353 |

LOCO per fold (coastguard / container / deadline), FLD on coefficient
features: direct 0.380 / 0.435 / 0.403, STC uniform 0.405 / 0.445 / 0.443; on
combined features 0.433 / 0.415 / 0.373 vs 0.460 / 0.435 / 0.420.  The
uniform-cost STC is ahead in every fold and feature set.

CNN (`latticezk_cnn_steganalysis`, sets `b1_magnitude` / `b1_adaptive`, GPU,
same 600 frame pairs; `benchmark/results/q2/adaptive_cnn_*.json`):

| Protocol | direct frame P_E (AUC) | STC uniform frame P_E (AUC) |
|---|---|---|
| LOCO | 0.457 (0.536) | 0.471 (0.511) |
| paired split | 0.463 (0.530) | 0.463 (0.533) |

The CNN is close to chance on both, as it already was on the magnitude
carrier (`docs/CNN_STEGANALYSIS.md`), so it shows no measurable difference;
the feature-based detectors remain the binding ones.

### Reading the numbers

* The gain is real but moderate: worst-case LOCO P_E 0.406 -> 0.431 and paired
  P_E 0.323 -> 0.388 at the same payload, with 26-47 % fewer changes and
  +1.4 to +2.4 dB PSNR.  With 200 test pairs per fold the standard error of a
  fold's P_E is about 0.03, so single folds are not significant on their own;
  the consistency across all folds and feature sets is the evidence.
* The gain scales with spare carriers: coastguard (rate 0.86 bits per carrier)
  saves 26 % of the changes, container and deadline (rate 0.6-0.65) 45-47 %.
  More frames per envelope (a lower density) would help STC more than direct
  embedding, since STC uses every carrier instead of a prefix.
* The texture/magnitude cost did not help: it moved changes to large levels in
  textured macroblocks but needed 5-18 % more of them, and these detectors are
  mostly sensitive to the count.  A cost model that helps would have to be
  learned against the detector, or use cover-side information (below).

## Limitations

* Selection channel: the cost model uses only carrier-invariant data, so an
  attacker can recompute it from the stego video too (selection-channel-aware
  steganalysis).  This is moot for the shipped `uniform` model, and the keyed
  carrier order still hides which syndrome column a carrier belongs to.
  Because STC extraction never needs costs, a future model could use
  cover-only data (e.g. decoded pixel texture before embedding) that the
  attacker can only estimate.
* Same carriers: the modification is still LSB replacement of `|level|`;
  +-1 matching would change `|level| >> 1` and break carrier re-derivation.
  STC lowers the change count, not the asymmetry of each change.
* Fragility: every carrier of the segment now enters the code, so one
  corrupted carrier anywhere in a segment can break that segment's envelope
  (before, only the prefix mattered).  The proof's integrity checks are
  unchanged; this is about robustness, which the scheme never claimed.
* Cost: about 50 MB and 1 s per 50 k-carrier segment for the Viterbi
  (`h = 10`); end-to-end embed and verify times are within 5 % of direct
  embedding except deadline (+25 % embed, +20 % verify; one run each).
* Evidence size: 3 clips x 200 frames, one key per run, CIF QP 22 only.  The
  4CIF and long-clip behaviour was not measured.

## Tests

`src/runtest/test_adaptive_carriers.py` (53 tests): STC round trips over
heights 1-10 and rates 1 to 0.3, brute-force optimality on a small instance,
cost following, public deterministic parameters, invalid inputs; cost
invariance under arbitrary carrier toggles (toy and real video); contract
validation and refusal of unsupported settings; profile ids of the direct
contracts pinned to their 18c5123 values; coded-envelope extraction,
empty payloads, header/body tamper detection, fail-closed on missing carriers
and insufficient capacity; real-video adaptive round trip (positions and costs
recomputed from the stego equal the embedder's), segmented context ==
extraction, and byte-identical stego for the direct magnitude and T1 contracts
against digests recorded with 18c5123.

## Reproduce

```bash
# 200-frame cuts (all-intra, so any cut is exact); same for coastguard, deadline
ffmpeg -i data/encoded/container_cif_q22_g1.h264 -frames:v 200 -c copy tmp/b1/cuts/container_200.h264
export ZKSTEGO_ANALYSIS_WORKERS=2
python -m benchmark.latticezk_adaptive_sim --videos tmp/b1/cuts/{container,coastguard,deadline}_200.h264 \
    --work tmp/b1/sim --output benchmark/results/q2/adaptive_sim.json          # ~25 min
python -m benchmark.latticezk_adaptive_e2e --covers tmp/b1/cuts/{container,coastguard,deadline}_200.h264 \
    --work tmp/b1/work --output benchmark/results/q2/adaptive_e2e.json          # ~75 min, sequential
python -m benchmark.latticezk_cnn_steganalysis --encoded-dir tmp/b1/cuts --stego-dir tmp/b1/work \
    --reports-dir tmp/b1/work --cache-dir tmp/b1/cnn_cache train --set b1_adaptive --protocol loco \
    --output benchmark/results/q2/adaptive_cnn_adaptive_loco.json             # ~5 min on an RTX 3060
```

One CIF E2E process was observed at about 0.65 GB resident.
