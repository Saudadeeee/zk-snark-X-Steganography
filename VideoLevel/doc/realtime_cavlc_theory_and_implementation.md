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
3. It is not a trailing-one coefficient, because CAVLC treats those levels
   specially.
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
4. Re-encode only length-invariant blocks, then rewrite RBSP and emulation
   prevention bytes without changing unrelated NAL units.
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

## Blind extraction relationship

Blind extraction and realtime use the same sign-invariant candidate policy.
`src/blind.py` derives sign-only positions from the stego bitstream and secret
key. The native patcher must preserve this policy exactly; otherwise a stream
can be fast but cannot be extracted without a sidecar.
