# Verified Completion Plan

## Product boundary

The first releasable system is a constrained edge pipeline, not a generic
H.264 editor. It accepts Annex-B H.264 Baseline streams with CAVLC, 4:2:0,
frame macroblocks and no slice groups. The camera encoder configuration is
part of the interface and is pinned in the deployment manifest. Unsupported
syntax is rejected before a video is modified.

The payload is encoded only by changing signs of selected non-zero residual
coefficients. It is never placed in SEI, NAL headers, container metadata, or a
spatial-pixel fallback.

## Acceptance gates

No phase may be represented as complete solely by source inspection. Its exit
criteria must be recorded from an executable test or benchmark.

| Phase | Deliverable | Required evidence |
| --- | --- | --- |
| 1. Decoder correctness | Native slice/macroblock parser | CTest plus successful traversal of every macroblock in pinned fixtures |
| 2. Safe rewrite | Bit-exact selected-block replacement | Source and output pass FFmpeg `-v error -xerror`; unrelated NALs remain byte-identical |
| 3. Blind channel | Native candidate schedule and extractor | Correct-key recovery and invalid result for wrong key on decoder-valid output |
| 4. Stream channel | Bounded camera/HTTP adapter | Sustained run with queue accounting and no unreported drops |
| 5. Measurement | Reproducible benchmark runner | Raw CSV/JSON for capacity, PSNR, SSIM, throughput, p50/p95 latency, CPU and RSS |
| 6. Delivery | Edge package and theory document | Pinned encoder settings, deployment guide, limits and reproducible command list |

## Implementation sequence

### 1. Complete the native CAVLC reader

1. Preserve the tested first-luma-macroblock path as a regression target.
2. Implement macroblock address traversal for I slices, including neighbour
   state across macroblock boundaries.
3. Add I16x16 luma DC/AC and 4:2:0 chroma DC/AC residual categories required
   by the pinned encoder. Reject I_PCM and unsupported slice modes explicitly.
4. Traverse each pinned fixture to the RBSP trailing bits. Record the first
   failing NAL, macroblock, block and bit offset if parsing stops.

### 2. Implement length-safe native rewrite

1. Retain the exact syntax span of each decoded residual block.
2. Select only trailing-one sign flags or other coefficients whose re-encoded
   block has exactly the source bit length.
3. Re-encode the whole selected block, rebuild RBSP/EBSP, and retain every
   unmodified NAL byte-for-byte.
4. Enforce strict FFmpeg decode validation before publishing output. A failed
   candidate produces no output artifact.

### 3. Complete blind extraction

1. Define one canonical keyed ordering and domain separation for stream, NAL,
   macroblock and candidate identifiers.
2. Implement the same ordering in native embedding and extraction, with test
   vectors shared with the Python verifier.
3. Require complete payload recovery, proof verification and negative tests
   for wrong key, modified video and insufficient capacity.

### 4. Build the realtime boundary

1. Feed bounded Annex-B IDR segments from camera capture or an HTTP input
   adapter into the native patcher.
2. Keep proof generation off the capture path and cache it per epoch.
3. Publish a segment only after the configured decode-validation policy; the
   deployment setting must state whether validation is synchronous or sampled.
4. Measure p50/p95 patch latency, end-to-end latency, FPS, queue drops, CPU
   and RSS on the actual target device.

### 5. Produce trustworthy benchmarks and documentation

1. Run quality and resource benchmarks only over decoder-valid stego outputs.
2. Store command, fixture hash, encoder version, machine/device identity and
   raw results beside each chart.
3. Update the theoretical document with the exact CAVLC candidate policy,
   blind schedule, proof binding and the distinction between proof validity and
   video decodability.

## Non-negotiable limits

- A copied offline key cannot be made to expire cryptographically by the video
  pipeline alone. Time-limited use requires an online authorization service,
  trusted clock, or secure hardware key storage.
- A successful ordinary FFmpeg invocation is not decoder evidence because it
  can conceal damaged H.264 data. Strict decode validation is required.
- A native parser benchmark is not an embedding benchmark. Realtime may only
  be claimed after native rewrite, extraction and stream measurements all pass.
- If a camera encoder emits unsupported syntax, the correct result is a clear
  rejection or a separately implemented profile, not a hidden fallback.
