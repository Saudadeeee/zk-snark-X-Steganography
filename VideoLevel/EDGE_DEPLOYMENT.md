# Edge camera deployment: pixel-domain embedding

## Data plane

The edge path embeds proof bytes in the Y (luma) pixels of each YUV420P
camera frame. `zkstego_pixel_embed` uses two QIM cosets, not H.264 SEI, NAL
headers, side data, or a metadata track. It leaves the U/V chroma planes and
the byte length of every frame unchanged.

```text
camera / RTSP decode -> YUV420P -> native QIM luma embedder -> H.264 encoder -> camera sink
```

The proof is generated once per epoch by `ProofEpochCoordinator`, then supplied
to the native process as `--payload-hex`. A 129-byte Groth16 proof fits in one
CIF luma frame (352x288) with the default QIM settings.

## Build locally

```powershell
cmake -S native -B native/edge-build
cmake --build native/edge-build --config Release
ctest --test-dir native/edge-build -C Release --output-on-failure
```

## Run on the edge device

The native component is a binary YUV420P filter. It keeps stdin/stdout in
binary mode on Windows. The following shows the local plumbing; replace the
first `ffmpeg` input with the appropriate camera/RTSP capture command for the
target OS.

```powershell
cmd /c "ffmpeg -i camera-input -pix_fmt yuv420p -f rawvideo - ^| native\edge-build\Release\zkstego_pixel_embed.exe --width 352 --height 288 --payload-hex <PROOF_HEX> ^| ffmpeg -f rawvideo -pixel_format yuv420p -video_size 352x288 -framerate 30 -i - -c:v libx264 -profile:v baseline -g 30 stego.h264"
```

`ffmpeg` is only the local capture/decode/encode integration layer; the proof
embedding itself is native source in this repository and does not call a cloud
or third-party service.

## Realtime and quality gate

```powershell
py -3.12 -m benchmark.edge_realtime --width 352 --height 288 --frames 300 --fps 30
```

The benchmark writes `benchmark/results/edge_realtime_data.json` and fails if
native p95 embedding latency exceeds the frame interval, if frames are dropped,
or if raw-luma PSNR is below 40 dB. The current result uses a 129-byte payload,
matching the project proof size.

This test measures the native pixel operation. Before a production claim, run
the same target-camera encoder at its intended bitrate/QP and verify recovery
from decoded frames, PSNR/SSIM, camera-to-output latency, CPU/RSS, and zero
drops. Lossy H.264 parameters determine the final QIM error rate and cannot be
truthfully inferred from a raw-frame benchmark.

## Edge scheduler

`src.edge.realtime` remains the local control plane:

- `BoundedSegmentQueue` keeps camera latency bounded by dropping stale work.
- `ProofEpochCoordinator` prevents per-frame proof generation.
- `EdgeRealtimeBudget` records the target frame interval and acceptance rule.
- `AnnexBSegmenter` is available when the capture source supplies encoded
  IDR-aligned segments; it is not an embedding channel.
