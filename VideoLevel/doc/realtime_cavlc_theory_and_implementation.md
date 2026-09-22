# Realtime CAVLC Theory and Implementation

## Purpose and current status

This document defines the only acceptable realtime path for this repository:
patch H.264 Baseline CAVLC residual coefficients inside independently decodable
IDR segments. Payload bytes must not be carried by SEI, NAL headers, container
metadata, or a spatial-pixel fallback.

The repository currently has a tested realtime control plane in
`src/realtime_cavlc.py`. It bounds queue latency, reuses one proof per epoch,
and reports an acceptance result. The current Python CAVLC parser and
reconstructor remain batch implementations. Therefore the controller is not
evidence that pixel content has already been patched at camera-frame rate.

The first native data-plane layer is implemented in `native/`: Annex-B NAL
splitting and lossless reassembly, EBSP to RBSP conversion, RBSP
emulation-prevention insertion, and bounds-checked fixed-length patch plans
across multiple NAL RBSPs in one segment transform. It is tested with CTest,
including preservation of unmodified NALs during a patched-IDR segment round
trip. It also decodes the luma `total_zeros`/`run_before` residual tail for
every CAVLC `TotalCoeff` value from 1 through 16; the test suite exercises all
table columns and one tail from a real IDR RBSP. It is intentionally limited to
a patch plan and isolated residual primitives: native slice traversal,
candidate selection, full block re-encoding, and camera-segment E2E validation
remain required before deployment.

## CAVLC embedding theory

For an H.264 Baseline residual 4x4 block, let its quantized transform
coefficients in zigzag order be `c[0], ..., c[15]`. A CAVLC-safe sign channel
encodes one bit at coefficient `c[k]` as:

```text
bit 0: c'[k] =  abs(c[k])
bit 1: c'[k] = -abs(c[k])
```

The candidate must satisfy all of the following:

1. It is an AC coefficient, never DC.
2. Its magnitude is nonzero and its support does not change.
3. In the blind sign channel, it is a genuine CAVLC trailing-one sign flag;
   the flag offset is immediately after `coeff_token` and changing it must not
   alter any other CAVLC syntax bit. (The conventional LSB channel instead
   excludes trailing ones.)
4. Its re-encoded block has the same bit length as the source block.
5. The replacement must preserve a decodable slice and pass visual-quality
   policy.

Sign changes alter reconstructed pixels through the inverse transform while
keeping payload inside compressed video content. They are not metadata.

## Realtime segment protocol

```text
camera encoder (Baseline, CAVLC, short all-intra GOP)
  -> Annex-B IDR segmenter
  -> bounded queue
  -> native CAVLC parser and safe-position selector
  -> proof epoch cache
  -> native sign patcher and RBSP emulation-prevention rewrite
  -> H.264 output
```

`RealtimeCAVLCScheduler` follows three operational rules:

- Capture must never wait for proof generation or a slow patch.
- At overload, discard the oldest unprocessed segment; do not silently grow
  latency.
- A proof is generated once for an epoch and reused by its segments.

The output is acceptable only when queue drops are zero and p95 CAVLC patch
latency is at most the frame interval (`1 / FPS`) or an explicitly stricter
budget.

## Native patcher contract

The pending native implementation must expose this logical function:

```text
patch_idr_segment(annex_b_segment, proof_bytes, embedding_key) -> annex_b_segment
```

It must:

1. Parse SPS/PPS once per stream and parse each IDR slice incrementally.
2. Decode enough CAVLC syntax to locate selected luma residual levels and
   retain exact start/end bit offsets.
3. Derive deterministic, key-ordered safe candidates; one modification per
   block by default.
4. Re-encode only length-invariant blocks, then rewrite the selected RBSP,
   regenerate emulation-prevention bytes, and preserve unrelated Annex-B NAL
   units byte-for-byte.
5. Return an unchanged segment when its validated capacity is insufficient;
   report that condition as a controlled drop/failure, never partial silent
   embedding.
6. Expose per-segment parse, patch, proof-wait and total-latency metrics.

## Performance plan

The batch benchmark is not a realtime benchmark. A target device must measure:

| Metric | Acceptance rule |
| --- | --- |
| CAVLC parse plus patch p50/p95 | p95 <= frame interval |
| End-to-end camera latency | within deployment budget |
| Queue drops | zero at sustained target FPS |
| CPU and RSS | recorded per target device |
| Decodability | FFmpeg or hardware decoder accepts every output segment |
| Quality | PSNR and SSIM against source capture |
| Payload integrity | extracted proof verifies after every run |

Run the scheduler contract test with:

```powershell
py -3.12 src/runtest/test_phase9_realtime_cavlc.py
```

The native patcher must add an E2E camera fixture and replace this controller
only acceptance with measured CAVLC segment results before realtime can be
claimed.

### Current measured boundary

On the current audit machine, the Python streaming sign-candidate pass over
the first 10 IDR slices of `deadline_cif_q22_g1_600f.h264` (16,768,616 bytes)
selected 1,096 keyed positions in 1.997 seconds (5.008 slices/s). Its bounded
selector retained only the requested positions and the observed working set
stayed below 45 MB during a full-file scan. This is evidence for bounded
candidate-selection memory, not a realtime claim: 5.008 slices/s is below a
30 FPS camera target and the measurement excludes native patch/write, proof,
and decoder validation.

### Latest end to end negative result

The Python path is not a usable embedding path yet. On the audit machine, a
one-byte blind proof payload (1,072 bits) was scheduled and patched into
`foreman_cif_q18_g1_300f.h264` (300 all-intra frames) in 280.579 seconds.
The patcher reported all 1,072 positions applied and preserved the source
byte length (3,551,610 bytes), but the resulting stream was not valid: FFmpeg
reported H.264 macroblock/CAVLC errors when run with `-xerror`, and blind
verification returned `valid: False` after 276.849 seconds (557.428 seconds
total). A normal FFmpeg invocation can conceal these errors while returning
zero; it is not an acceptable decoder acceptance test.

`patch_selected_sign_positions_streaming` now validates its temporary output
with `ffmpeg -v error -xerror` before atomically publishing it. A decoder
error therefore aborts the operation and removes the temporary file. This is
a fail-closed safety gate, not a repair for the current multi-block CAVLC
patcher. Until native slice traversal and a bit-exact per-block rewrite are
implemented and pass decoder plus blind-proof E2E tests, this repository must
not claim realtime, edge-ready, or usable blind embedding.

### Native header traversal baseline

The native `zkstego_idr_inspect` tool scanned the 600-IDR
`deadline_cif_q22_g1_600f.h264` fixture in 501.974 ms on the audit machine.
It parsed the stream's SPS/PPS and all IDR headers, selected parameter sets,
parsed the first I-macroblock, and decoded its first luma CAVLC 4x4 residual
block. It did not traverse later macroblocks or residual blocks, select blind
candidates, patch signs, or validate an output decoder. This is a functional
and performance baseline for one native residual block per IDR only; it does
not establish a realtime steganography claim.

The native library now also has a luma-I4x4 macroblock traversal primitive. It
uses CAVLC's four coded-8x8-group order, derives `nC` from already decoded
left/top 4x4 neighbours, and has unit coverage for empty coded blocks. A
regression test also covers the `level_prefix == 14` CAVLC level-code branch.
It is not yet connected to the IDR inspector: an attempted run over the first
non-empty real macroblock stopped fail-closed at luma block 11 (bit 613,
`nC=6`) with an invalid coeff-token. That result prevents claiming full native
macroblock traversal until the remaining bit-exact residual decoding issue is
resolved against real fixtures.

## Blind extraction relationship

Blind extraction and realtime use the same sign-invariant candidate policy.
`src/blind.py` derives sign-only positions from the stego bitstream and secret
key. The native patcher must preserve this policy exactly; otherwise a stream
can be fast but cannot be extracted without a sidecar.
