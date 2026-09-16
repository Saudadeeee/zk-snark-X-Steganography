# Realtime Transport Contract

The repository now has a bounded-latency H.264 Annex-B transport layer in
`src.realtime`. It is a live-stream foundation, not a claim that the current
Python CAVLC patcher can encode arbitrary video in realtime.

## What runs now

- Incremental Annex-B parsing across arbitrary pipe/network chunks.
- AUD-delimited access-unit assembly (`NAL type 9` is mandatory).
- A bounded queue that drops old non-IDR frames before a new IDR frame.
- IDR-only scheduling of compact payload chunks.
- Fail-open forwarding: if a live mutator fails, the original access unit is
  forwarded unchanged and the failure is counted.

The contract tests run with:

```powershell
py -3.12 src/runtest/test_realtime_transport.py
```

## Upstream encoder profile

The live sender must emit H.264 Baseline/CAVLC Annex-B with AUD NAL units. A
representative FFmpeg encoder command is:

```bash
ffmpeg -re -i INPUT -c:v libx264 -profile:v baseline -coder 0 \
  -x264-params "aud=1:keyint=30:min-keyint=30:scenecut=0" -f h264 pipe:1
```

The keyframe cadence is a capacity/latency trade-off: payload may be scheduled
only on a complete IDR access unit. The relay does not infer access-unit
boundaries from partial slice headers.

## Required production backend

`RealtimeAnnexBRelay` accepts an `AccessUnitMutator` callback. A production
backend must be native (C/C++/Rust, built on FFmpeg/libavcodec or an equivalent
encoder integration) and must, for every mutated IDR unit:

1. retain CAVLC syntax validity and exact NAL framing;
2. apply only candidates accepted by bit-length and forward-decode checks;
3. finish within the configured frame deadline; otherwise return the original
   access unit;
4. emit applied-carrier telemetry so the receiver can distinguish a skipped
   chunk from a valid embedding.

The existing Python file-oriented reconstructor is deliberately not installed
as that callback: its whole-file analysis and reconstruction latency makes it
unsafe to market as realtime. The compact ML-DSA receipt/reference path is the
appropriate payload source for the live scheduler; Groth16 proving belongs to
an asynchronous control plane, not the per-frame hot path.

## Native C direct-video path

`native/` now includes a C17 direct CAVLC coefficient carrier. It changes the
magnitude parity of one high-frequency, already-nonzero AC coefficient by at
most one. The rule preserves nonzero support and permits deterministic
extraction from the decoded coefficient stream.

The generic Annex-B relay remains transport-only. It may expose an SEI
diagnostic path, but SEI is explicitly excluded from the direct-video stego
pipeline. Direct CAVLC mutation is safe only in an encoder fork after
quantization and before inverse transform/reconstruction; otherwise reference
frames can drift. The native x264 adapter selects Baseline/CAVLC specifically
for that fork integration.

## Next implementation decision

The native backend depends on the deployment target and transport: x86/Linux
or Raspberry Pi, plus RTSP/SRT/WebRTC. Those choices set the decoder API,
hardware acceleration path, and a measurable latency target; they cannot be
chosen interchangeably after the wire protocol is fixed.
