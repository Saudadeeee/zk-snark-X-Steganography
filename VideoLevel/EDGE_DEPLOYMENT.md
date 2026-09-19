# Edge camera deployment

## What is real-time today

The rebuilt native `zkstego_annexb_relay` is a local Annex-B H.264 transport
component. It keeps arbitrary video bytes intact and may inject a small
proof/epoch metadata payload as an SEI NAL immediately before an IDR. On the
current machine and `akiyo_cif_q22_g1.h264`, the measured transport path was
48.77 MiB/s with 8.68 ms p95 segmenter ingress at a 30 FPS target.

This is not a claim that current CAVLC proof embedding is real-time. The Python
CAVLC core still performs whole-segment analysis and reconstruction; SEC6
measures that separately. Do not label a deployed system "realtime ZK stego"
until its CAVLC segment patcher has passed the same FPS, p95 and visual-quality
acceptance benchmark.

## Build locally

```powershell
cmake -S native -B native/edge-build
cmake --build native/edge-build --config Release
ctest --test-dir native/edge-build -C Release --output-on-failure
```

## Camera transport

The relay consumes and produces raw Annex-B H.264 on standard input/output.
Run it locally after configuring the camera encoder for IDR-aligned H.264.

```powershell
cmd /c "native\edge-build\Release\zkstego_annexb_relay.exe --sei-payload-hex 5A4B535445474F < camera.h264 > stego-transport.h264"
```

In production connect the camera/RTSP decoder to the relay with binary pipes;
do not route frames through a text shell or cloud service. The native relay
forces binary stdin/stdout on Windows to avoid `0x1A` truncation.

## Edge scheduler

`src.edge.realtime` supplies the local control plane:

- `AnnexBSegmenter`: emits completed IDR-delimited segments.
- `BoundedSegmentQueue`: caps latency by dropping the oldest queued segment.
- `ProofEpochCoordinator`: makes one proof per epoch, not one proof per frame.
- `EdgeRealtimeBudget`: requires p95 latency within the target and zero drops.

The application must provide the actual segment processor. Initially that can
be the existing Python embedder for batch/near-real-time operation. Realtime
CAVLC embedding requires a native segment patcher with the same safety filter,
proof framing and verifier as the Python core; this is the next implementation
milestone, not a property of the relay.

## Benchmark each target device

```powershell
py -3.12 -m benchmark.edge_realtime `
  --input data/encoded/akiyo_cif_q22_g1.h264 --fps 30
```

The command writes `benchmark/results/edge_realtime_data.json`. Record the
device model, encoder configuration, resolution, FPS, p50/p95 ingress, relay
throughput, queue drops, CPU, RSS, CAVLC segment latency and PSNR/SSIM before
declaring a device production-ready.
