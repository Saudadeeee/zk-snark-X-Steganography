# Capacity-adaptive chunking (stream C1, ZKBC v2)

Status: opt-in transport contract. `CarrierProfile(..., chunk_plan=AdaptiveChunkPlan(...))`
in `src/lattice_zk/video_pipeline.py` switches a profile to it. Profiles without
a plan use the old fixed-size ZKBC v1 transport. Their profile ids, policy
hashes, public sync keys, v1 chunk bytes and v1 segmented digest are the same
as at commit `10bce11`: the 98-entry baseline table is pinned by
`test_existing_profiles_and_v1_framing_are_byte_identical` in
`src/runtest/test_adaptive_chunking.py`.

| file | role |
|---|---|
| `src/adaptive_chunks.py` | plan (`AdaptiveChunkPlan`, `plan_layout`), ZKBC v2 framing, canonical check |
| `src/blind_sync_adaptive.py` | transport: per-segment capacity, context, embed, blind extract |
| `src/lattice_zk/video_pipeline.py` | `CarrierProfile.chunk_plan`, profile id, verifier canonical check |
| `benchmark/latticezk_video_e2e.py --adaptive-chunks` | real end-to-end run |
| `benchmark/latticezk_adaptive_chunk_plan.py` | capacity-planning dry run on the scans |

## Problem

The fixed transport splits the envelope (8 165 B registered or 14 885 B in-band
with `bdlop-open-128-v2`) into chunks of a single pinned size,
`profile.chunk_bytes`. Chunk *i* goes into 100-frame segment *i*, so the
smallest segment that has to carry a chunk caps the size of every chunk. A
segment with low capacity cannot be skipped. The verifier re-chunks the
envelope under the pinned size and requires byte equality (fix D1), so the
embedder has no room to adapt either.

## Format

Each carrier segment still holds one ordinary blind-channel envelope (ZKVP,
14 B: magic, version, kind, length, CRC-32). Its payload is one ZKBC v2 chunk:

```text
offset size field          value (all fixed by the plan)
0      4    magic          "ZKBC"
4      1    version        2
5      2    chunk_index    0, 1, 2, ... (no gaps)
7      2    segment_index  transport segment that carries this chunk
9      4    total_size     payload (envelope) length
13     4    offset         byte offset of this chunk in the payload
17     4    total_crc      CRC-32 of the whole payload
21     -    part           payload[offset : offset + size]
```

The framing costs 35 B per carrier segment, against 37 B for v1 (14 + 23).
The header has no chunk-count field and no chunk-size field. The part length
comes from the ZKVP length and must equal the planned size. The count is the
number of chunks the plan produces. A v1 reader rejects v2 chunks (version
byte), and the reverse holds too.

## Plan

`AdaptiveChunkPlan` (frozen, every field an integer, all of them in the profile id):

| field | default | meaning |
|---|---|---|
| `version` | `zkbc-v2-greedy-fill-v1` | algorithm id |
| `min_chunk_bytes` | 256 | segments whose usable chunk is smaller are skipped |
| `reserve_bits` | 0 | carriers left unused per segment |
| `fill_permille` | 1000 | fraction of each segment's carriers that may be used (density) |
| `max_chunk_bytes` | 65 535 | cap per segment |

For a segment with `C` capacity bits:

```text
usable_bits  = C * fill_permille // 1000 - reserve_bits
usable_bytes = usable_bits // 8 - 35            (ZKVP + ZKBC v2 framing)
chunk_cap    = 0 if usable_bytes < min_chunk_bytes else min(usable_bytes, max_chunk_bytes)
```

`plan_layout(P, capacities, plan)` walks the segments in order. A segment with
`chunk_cap = 0` is skipped. Otherwise it takes `min(remaining, chunk_cap)`
bytes. The walk stops when the payload is placed, and raises if the video
runs out of segments first. Greedy filling is optimal for the span: any
feasible plan has placed at most as many bytes as greedy by every segment
index, so greedy ends at the earliest possible segment. That keeps the number
of segments the verifier has to analyse as low as possible.

**Capacity** (`blind_sync_adaptive.segment_capacity_bits`) is the number of
stable, patchability-checked carriers of the operating contract,
`len(derive_blind_positions_operating_contract(segment, key, ∞, contract))`.
Under direct contracts (magnitude LSB, T1 sign) one carrier holds one envelope
bit. Under STC contracts (`AdaptiveOperatingContract`) the capacity is
`available − 112·header_carriers_per_bit + 112`, which is exactly the
condition of `coded_carrier_layout`. The count does not depend on the sync
key, because the key only permutes the set. The default
`header_carriers_per_bit = 1` gives the same capacity as the direct contract.

## Binding

* **Profile id**: when a plan is present, the carrier-profile description
  drops `chunk_bytes` and adds `chunk_plan` (the plan descriptor). Every plan
  parameter therefore changes `profile_id`, the policy hash, the relation id,
  the pins and the session binding. `chunk_bytes` must stay at its default
  with a plan, so two ids cannot describe the same transport.
* **Video digest**: for adaptive profiles, `D` uses its own domain:
  ```text
  D = SHA-256("zkstego/canonical-h264-segmented-adaptive/v1\0" ‖ plan_id ‖
              u32 F ‖ u32 P ‖ u32 L ‖
              (u32 i ‖ u32 frames_i ‖ u8 role_i ‖ u64 capacity_i ‖ u32 chunk_i ‖ d_i)_{i<L})
  ```
  The roles are `0` unused (after the payload), `1` skipped (analysed, below
  threshold) and `2` carrier. As before, `d_i` is the carrier-normalised
  digest for carrier segments and the file SHA-256 for every other segment, so
  skipped segments are bound byte for byte. The statement covers `D`, so it
  covers the capacities, the roles and the chunk sizes as well.
  `plan_id = SHA-256("zkstego/adaptive-chunk-plan/v1\0" ‖ JSON(plan))`.

## Why it is blind

The extractor recomputes every segment's capacity from the stego video. A
carrier segment's capacity is unchanged by embedding:

* a magnitude carrier is the LSB of a `|level| ≥ 4` non-trailing-one AC
  coefficient, and flipping it keeps `|level| ≥ 4`, the zero pattern, the
  trailing ones and total coefficients, hence nC and every CAVLC length
  (`src/core/stego.py`, bit-length invariance check);
* the choice of carrier inside a block is made symmetric under the flip by
  `select_rederivable_stable_candidate`: an earlier candidate is rejected if
  it is safe either before or after the selected flip, and the flip is its own
  inverse;
* trailing-one sign flips keep the trailing-one structure, and STC rewrites
  the same carrier set;
* skipped and unused segments are byte-identical copies.

So the stable set of every segment, and with it its count, is the same in
cover and stego. The existing blind extraction already relies on this,
because the keyed order is a shuffle of the whole set. With the same
capacities, the same pinned plan and the pinned envelope size
(`envelope_size(params)`), the verifier derives the same layout. Checked
empirically: in the 30-frame fixture test (magnitude and STC) and in the E2E
below, the capacities, layout, `positions_hash` and `D` recomputed from the
stego video equal those derived from the cover. If the invariance ever failed,
verification would fail closed (false reject), never accept.

## Why it is canonical (D1 stays fixed)

Every header field and every chunk length is a function of the plan, the
capacities and the payload. The transport checks each chunk against the
incremental plan while it extracts, and recomputes the whole layout at the
end. The pipeline then recomputes
`pack_adaptive_chunks(payload, plan_layout(len(payload), capacities, plan))`
itself and requires byte equality with the extracted chunks. The capacities
must end at the segment that completes the payload, and a reported layout must
equal the recomputed one. Tests reject each of the following:

| attack | test |
|---|---|
| any header field +1 (chunk/segment index, total, offset, CRC) | `test_any_rewritten_header_field_is_rejected`, `test_pipeline_rejects_rewritten_chunk_headers` |
| self-consistent re-chunking of the same envelope | `test_rechunked_reordered_truncated_or_extended_sets_are_rejected`, `test_pipeline_rejects_rechunked_truncated_or_extended_envelopes` |
| reordered, dropped, duplicated, truncated, extended chunks | same |
| embedder/verifier plan mismatch | `test_embedder_verifier_plan_mismatch_is_rejected`, `test_extractor_rejects_chunks_that_deviate_from_the_plan` |
| transport capacities that disagree with the video, or extra ones | `test_capacity_reports_that_disagree_with_the_video_are_rejected` |
| chunk claiming another segment, short chunk, other payload size | `test_extractor_rejects_chunks_that_deviate_from_the_plan` |

## Codec policy v2, STC and GOP > 1

* **Codec policy v2** (D5, `CarrierProfile.codec_policy`) composes with a plan.
  The profile description carries both `"codec_policy"` and `"chunk_plan"`.
  The transport receives `digest_policy`, which enforces the pinned
  access-unit partition, applies the v2 carrier-normalised and raw-segment
  digests, and switches the combined digest to the domain
  `zkstego/canonical-h264-segmented-adaptive/v2`, which also binds
  `SEGMENTATION_RULE_V2` (`test_plan_and_codec_policy_v2_are_bound_together`).
  The CIF E2E below ran under v1.
* **STC**: `segment_capacity_bits` accounts for the header code, and the
  per-segment embed and extract paths are those of `blind_sync`, unchanged.
  The fixture test runs on both magnitude and STC carriers.
* **GOP > 1**: the profile's `gop_policy` is passed through. Every segment is
  inspected (`_inspect_segments`), and positions are globalised by coded
  slices, as in the fixed transport
  (`test_gop_segments_offset_positions_by_coded_slices`).

## Results

### Real E2E (CIF, registered `bdlop-open-128-v2` envelope)

Report: `benchmark/results/q2/adaptive_chunk_e2e_uneven_cif_q22_reg.json`.

The cut is 300 CIF frames, QP 22, all-intra Baseline, built so that capacity
is uneven across segments: 100 frames each of coastguard, akiyo and container.

```text
ffmpeg -i coastguard_cif.y4m -i akiyo_cif.y4m -i container_cif.y4m -filter_complex \
  "[0:v]trim=end_frame=100,setpts=PTS-STARTPTS[a];[1:v]trim=end_frame=100,setpts=PTS-STARTPTS[b];\
   [2:v]trim=end_frame=100,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1[v]" -map "[v]" \
  -c:v libx264 -profile:v baseline -g 1 -bf 0 -qp 22 -f h264 tmp/uneven_cif_q22_g1_300f.h264
python -m benchmark.latticezk_video_e2e --video tmp/uneven_cif_q22_g1_300f.h264 \
  --output tmp/adaptive_e2e/uneven_stego.h264 \
  --report benchmark/results/q2/adaptive_chunk_e2e_uneven_cif_q22_reg.json \
  --registered --carrier magnitude --adaptive-chunks --min-chunk-bytes 2048
```

| item | value |
|---|---|
| envelope | 8 165 B registered, `bdlop-open-128-v2` |
| segment capacities (cover = recomputed from stego) | 31 404 / 10 501 / 50 757 bits |
| layout | segment 0: 3 890 B (fills it within 4 bits), segment 1: **skipped** (1 277 B usable < 2 048), segment 2: 4 275 B |
| fixed ZKBC v1, any chunk size | does not fit (segment 1 caps a chunk at 1 275 B, so 7 segments needed) |
| IDR slices changed | 200 of 300; segment 1's 100 slices byte-identical |
| blind video-only verification | **valid** (`ok`), 217 s; embed 500 s |
| replay of the consumed session | rejected |
| one-bit tamper (middle of file) | rejected |
| one-bit tamper in the skipped segment | rejected |
| verification under another plan (`min_chunk_bytes` 1 024, own registry) | rejected (segment 1 then has to carry a chunk: "blind payload magic mismatch") |
| decoded quality | PSNR 44.08 dB, SSIM 0.9996 |
| peak RSS | 1.33 GB (`ZKSTEGO_ANALYSIS_WORKERS=2`) |

Both tamper bits landed inside CAVLC residual data, so the strict parser
rejected them ("untrusted CAVLC parse offsets"). A change to a skipped segment
that still parses is caught by its byte-level `d_i` instead
(`test_non_carrier_change_or_other_session_is_rejected` on the stand-in
channel). The default plan (`min_chunk_bytes` 256) would use all three
segments here (3 890 + 1 277 + 2 998 B). The 2 048 B threshold was chosen to
exercise skipping.

### Capacity-planning dry run on the 4CIF scans

`python -m benchmark.latticezk_adaptive_chunk_plan --output benchmark/results/q2/adaptive_chunk_plan_4cif.json`
(default plan, `fill_permille = density`). "sweep" is the sweep's fixed-chunk
rule, which sizes the chunk at 97 % of the smallest scanned segment. "best
uniform" is an exhaustive search over every fixed chunk size.

| case | scanned | sweep | best uniform | adaptive, v2 (8 165 B) | adaptive, v1 (7 589 B) |
|---|---|---|---|---|---|
| crew4cif_q22_reg | 6/6 | no | no | **does not fit**: 7 757 B usable in 600 frames, 408 B short | fits, segments 0–5 |
| soccer4cif_q22_reg | 3/6 | no | yes | **fits, segments 0–1** (4 784 + 3 381 B) | fits, segments 0–1 |
| crew4cif_q22_reg_d50 | 6/6 | no | no | does not fit (half of 7 757 B) | does not fit |
| crew4cif_q22_reg_d25 | 6/6 | no | no | does not fit | does not fit |
| soccer4cif_q22_reg_d50 | 3/6 | no | no | undetermined: 2 828 B more needed from 3 unscanned segments | undetermined (2 252 B) |
| soccer4cif_q22_reg_d25 | 3/6 | no | no | undetermined: 5 532 B more needed | undetermined (4 956 B) |
| crew4cif_q18_reg (ref.) | 6/6 | yes | yes | fits, segments 0–1 | fits |
| city4cif_q22_reg (ref.) | 3/6 | yes | yes | fits, segment 0 | fits |
| harbour4cif_q22_reg (ref.) | 3/6 | yes | yes | fits, segments 0–1 | fits |

Reading:

* **soccer Q22** now fits in 200 frames. The uniform rule failed only because
  scanned segment 2 holds 3 501 bits. An exact fixed chunk (4 782 B) would also
  fit, but the adaptive plan needs no scan-dependent size choice.
* **crew Q22**: the claim that "total capacity suffices" does not hold for the
  production envelope. The six segments sum to 63 756 bits = 7 969 B, below
  the 8 165 B envelope even before framing. No chunking can fit it into these
  600 frames; this needs more carriers (a different carrier, a lower QP, or a
  longer clip). With the 7 589 B v1 envelope, the one the original capacity
  scan was sized for, the adaptive plan fits using all six segments, and no
  fixed chunk size does.
* **crew d50/d25** use half or a quarter of an already insufficient capacity,
  so they are impossible. **soccer d50/d25** depend on the three segments that
  were never scanned. Scanning them was not done here, because it is a 4CIF
  workload on the shared machine.

## Limits

* Capacity invariance is a property of the stable carrier rules, not of the
  plan. A contract without invariant carriers cannot use this transport (it
  requires `stable_carriers_only` and patchability checking).
* The verifier analyses every segment up to the last carrier, skipped ones
  included, so skipping saves embedding changes but not verifier time.
* The greedy plan concentrates the changes in the first segments, at up to
  full density there. `fill_permille`, `reserve_bits` and `max_chunk_bytes`
  spread them, at the cost of more segments.
* The plan is fixed per profile. Changing the threshold or density means a new
  relation in the registry.
* The limits are 65 535 segments, 65 535 chunks and payloads up to 16 MiB.
  The chunk size is bounded by `max_chunk_bytes` (≤ 16 MiB).
