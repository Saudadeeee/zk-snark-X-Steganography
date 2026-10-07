# Completion Plan and Evidence Audit

> **Update 2026-10-02.** The test counts below are from 2026-09-24. The current
> suite has 12 phases plus the hardware phase H1; `run_all.py` passed 161/161 on
> 2026-10-07 (see README), after native channel protocol v2 (HKDF subkeys, bit
> whitening), protocol v3 (no HMAC frame tag; the Groth16 proof authenticates) and the
> bit-constrained circuit (63,321 constraints, new local keys).
> Earlier camera and media records were made with protocol v1 and the old circuit.
> The Python media pipeline (Phases 4/5/8 below) was removed the same day; only the
> native core remains.
> The 7.608 FPS camera figure predates the 2026-10-02 native
> stdin-reader and bit-reader speed-up (a 1080p all-intra live embed went from
> 30.1 s to 2.5 s on the development host) and has not been re-measured.

## Product boundary

The supported data plane is a constrained Annex-B H.264 Baseline/CAVLC profile:
progressive 8-bit 4:2:0, single supported IDR slice per segment, frame
macroblocks, and the pinned all-intra camera-encoder settings. It changes signs
of selected non-zero CAVLC trailing-one residual coefficients. It does not use
SEI, container metadata, or pixel-domain fallback, and rejects unsupported
syntax instead of guessing.

## Current acceptance status

| Gate | Current evidence | Status |
| --- | --- | --- |
| Native traversal | Full-slice CTest covers 300 pinned IDRs / 118,800 macroblocks including I16x16 and 4:2:0 chroma; strict-decode source fixture. | Passed for pinned profile; not generic H.264. |
| Length-safe rewrite | Native sign rewrite regression reparses candidate map; native CLI fixture output passes FFmpeg strict decode on Windows and Linux. | Passed for pinned profile. |
| Blind authenticated extraction | Correct-key payload recovery and wrong-key rejection in native CLI fixture E2E and live-camera WebSocket E2E; Groth16 proof verifies after camera extraction. | Passed functionally. |
| Bounded stream | Authenticated WebSocket feeds native incremental NAL processing; fixture and camera loopback TCP E2E pass with bounded drains and zero drops. | Functionally passed on development host. Corrected source-preserving camera run observed only 7.608 FPS; edge and non-loopback transport pending. |
| Benchmark | JSON records capacity, PSNR/SSIM, encoded output and source-preserving FPS, camera-pipe-to-WebSocket-loopback-TCP NAL p50/p95 and client/server stage percentiles, native latency, CPU/RSS, strict decode, camera/encoder/toolchain identity and CLI hash. | Reproducible host evidence; no edge-device result. Earlier default-sync FPS counts include synthetic duplicates and are not camera FPS evidence. |
| Theory and deployment docs | CAVLC rules, blind schedule, proof boundary, unsupported syntax, run commands, and benchmark results are documented. | Theory and a target manifest template are present; measured target manifest still pending. |

Authoritative evidence is in `native/tests/cavlc_stream_tests.cpp`,
`src/runtest/test_native_cli_fixture.py`,
`src/runtest/test_native_camera_http.py`,
`src/runtest/test_native_http_channel.py` (including a real loopback Uvicorn /
WebSocket TCP round trip), and
`benchmark/results/realtime_camera_runs_20260924.json`. On 2026-09-24 the
full Python suite passed **99/99** after the first test-runner exit-code fix,
including public proof-payload verification, bounded-buffer validation, TCP
latency decomposition, and Phase 12's real loopback Uvicorn/WebSocket E2E. A
subsequent hardening change also rejects phases that report zero tests or
reported failures despite exit code 0. After the latest recorder and harness
changes, the quick suite passed **88/88**, including Phase 11 at **35/35** and
Phase 12 at **5/5**; the full suite then passed **108/108** across Phases
1 and 4–12. Phase 5 alone took roughly 17 minutes on this host and peaked at
about 3.9 GB private memory during the run, so this full suite is not a fast
development feedback loop. The recorder's
machine-readable active-FPS gate derives FPS from emitted frame count / active
duration (rather than rounded reported FPS) and retains reported FPS only for
diagnostics. Phase 11
also rejects incomplete/non-finite records, missing encoded-byte/channel-
latency metrics, bounds a pending input chunk in stdin-flow measurements,
checks FPS/frame-duration mismatches, requires a positive camera input-buffer
bound, validates native stdout-read-wait/NAL-interarrival percentiles, and
asserts the runner never returns success for failed/empty phase results.
New runs include `active_fps_gate`, comparing emitted frames / active duration
with the requested 30 FPS and retaining FFmpeg's reported FPS separately for
diagnostics. A regression test covers a rounded report of 30.0 when 151 frames
over 5.076 seconds is actually below threshold. Corrected camera run 24
measured 7.608 FPS and fails that gate; existing append-only historical
records were not rewritten.
Phase 1 was rerun separately after adding a real-Groth16 negative check for
changing only the public payload length; it passed **9/9**.
The camera TCP run 2 passes the stricter recorder schema and exercises the
public proof verification API against a freshly extracted camera payload.
The Linux x86-64 build passed CTest 1/1 and a real CLI
fixture round trip with strict FFmpeg decode, exact blind payload recovery, and
wrong-key rejection.
On 2026-09-24, the current Windows Release native test target rebuilt with
MSBuild 17.14.51 and CTest passed **1/1** in 76.92 seconds, revalidating the
full pinned-profile traversal/rewrite test against the current worktree.
The latest same-day rerun also passed CTest **1/1** (76.78 seconds); after
that rebuild, the native CLI fixture E2E passed **1/1** (strict FFmpeg exit 0,
3,551,610-byte output, correct-key match, wrong-key rejection) and the native
HTTP/WebSocket channel E2E passed **5/5**, including the loopback Uvicorn TCP
round trip.
Physical-camera run 21 is a 60-second host soak with reproducibility metadata
and proof-bearing E2E. It records 1,801 frames at 29.977 active arrival FPS,
zero drops, strict decode, decoded quality, capacity, latency and resource
metrics. Paired NAL completion arrivals from the FFmpeg stdout pipe to the
WebSocket TestClient are p50/p95 2.2267/125.257 ms (5,404 NALs); the high tail
is material. This in-process measurement excludes sensor exposure and real
TCP/TLS. These results do not demonstrate an ARM/SoC target, end-to-end camera
latency, thermal stability, or production readiness.

The newer physical camera run 2 is recorded at
`benchmark/results/realtime_camera_tcp_decomposed_20260924.json`. It is a
60-second UVC → FFmpeg → Uvicorn/WebSocket loopback TCP → native CAVLC soak:
1,801/1,801 frames at 29.979 active FPS, zero drops, strict FFmpeg decode,
blind payload extraction, Groth16 verification and negative-key/message checks
all passed. Across 5,404 NALs, loopback TCP latency was p50/p95
1.2775/128.5626 ms. The measured p95 components were camera-read-to-client-send
return 0.2847 ms, client-send-return-to-receive 128.4907 ms, server native
stdin write+drain 0.0321 ms, and native stdout-to-WebSocket-send 0.2052 ms;
native payload patch p95 was 12.4047 ms. Thus the observed tail occurs after
the client send call returns and before the client receives the corresponding
output, not in measured server send/drain spans. The result does not isolate
kernel/TCP scheduling from client receiver scheduling, and is not LAN/TLS or
sensor-to-output latency.

Two 60-second async-client measurements then captured input/output NAL
interarrival and native stdout-read wait. With DirectShow's input-buffer bound
reduced from the earlier 64 MiB setting to 1 MiB, p95 loopback latency was
127.5855 ms; at 256 KiB it was 127.4311 ms. Both runs captured 1,801 frames,
zero drops, and passed proof and strict-decode gates. On the 256 KiB run,
input/output NAL-completion interarrival p95 was 125.7893/126.1756 ms, native
stdout-read-wait p95 145.1017 ms, server stdout-to-WebSocket-send p95 0.1992 ms,
and client send-start-to-receive p95 127.276 ms. The older 64 MiB run measured
loopback p95 128.0479 ms and input/output interarrival 126.1165/126.707 ms.
Those small differences across changing live scenes are not evidence that
buffer reduction fixes the tail. The 256 KiB run had no drops in this sample
and is retained as the development harness setting to cap queued capture data;
it is not yet qualified for other cameras or environments. The close input /
output interarrival distributions and high stdout read wait suggest (but do not
prove) that bursty DirectShow/FFmpeg input timing contributes most of the tail;
the camera supplies no usable frame timestamps here, so sensor-to-output
latency remains unmeasured.

Run 22 extends the same 256 KiB DirectShow-buffer configuration to a 300-second
physical-camera soak, recorded in `benchmark/results/realtime_camera_runs_20260924.json`.
It captured and emitted 8,999/8,999 frames (29.997 active FPS; 29.869 FPS
including startup), with zero dropped chunks. Strict FFmpeg decode passed,
correct-key blind extraction matched, Groth16 verified, and wrong-key plus
changed-message checks rejected. The 26,998-NAL loopback-TCP measurement was
p50/p95 1.299/127.9583 ms; input/output NAL interarrival p95 was
126.2041/126.8606 ms. Native stdout-read-wait p95 was 145.5923 ms, while
stdout-to-WebSocket-send and stdin-write/drain p95 were 0.197/0.0337 ms.
Payload-bearing native patch p50/p95 was 8.5508/9.5462 ms across 22 IDRs;
all-IDR service p95 was 0.0384 ms (4,096 samples, sample cap). Quality was
79.8169 dB full-video YUV420 PSNR, 48.5743 dB minimum modified-frame PSNR and
0.99999771 mean luma SSIM. Full-stream capacity was 575,936 bits over 8,999
IDRs; capacity analysis took 54.902 s after capture and is not a live-path
cost. The capture-stage process-tree sampler recorded 259,338,240-byte peak
RSS and 60.922 CPU seconds over 309.022 seconds; native-child peak RSS/CPU was
5,283,840 bytes/1.094 seconds. These capture-scoped measurements exclude
post-capture decode/quality/capacity analysis and Groth16 generation/verification.
Despite the longer soak, the ~128 ms p95 tail remains; this is stronger host
stability evidence, not evidence of low-latency sensor-to-output behavior or
edge-device performance. This run used FFmpeg's default raw-H.264 CFR
synchronization; its output frame cadence is not a camera sensor FPS result.

An initial capture-only diagnostic challenged the earlier nominal 30-FPS
readings; its first interpretation is superseded by the raw-H.264 muxer
comparison and corrected E2E below.
On the same named UVC device and requested 352x288@30 mode, DirectShow raw
YUYV422 passthrough delivered 450 complete frames in 60 seconds (7.5 FPS),
with frame-completion interarrival p50/p95 128.3263/156.99 ms. Independent
MJPEG passthrough also yielded 450 frames (p50/p95 129.989/155.3098 ms). A
20-second initial libx264 test emitted 150 frames in each mode because it
targeted FFmpeg's null muxer; it did not exercise raw-H.264 output duplication.
The actual raw-H.264 comparison in the correction below revises the interpretation of the
earlier 29.97–29.997 FPS E2E arrival counts. The probe used the same requested
device mode but a separate, unpaired camera session; DirectShow/Annex-B timing
has no reliable sensor PTS here. Treat actual 30-FPS acquisition as unverified
until exposure/driver configuration and source-vs-encoded frame accounting are
resolved. The reproducible command records and measurements are in
`benchmark/results/realtime_camera_capture_rate_diagnostic_20260924.json`.
The high NAL interarrival tail is therefore not yet attributable to transport
or native processing; under this observed camera condition the source itself
delivers at only about 7.5 frames/s.

The source-rate diagnostic host is an ASUS TUF Gaming F15 FX507ZM running
Windows 11 Pro build 26100, with the built-in `USB\VID_13D3&PID_56A2&MI_00`
camera using Microsoft's `USB Video Device` / `usbvideo.inf` driver version
10.0.26100.9444. A read-only `IAMCameraControl::GetRange/Get` query reports
auto exposure enabled at -6 log2 seconds (1/64 s), with manual range -8 to 0
(1/256 s to 1 s); no `Set` call was made. Since the reported value is shorter
  than 1/30 s, simple long-exposure throttling is not established as the cause
  of the 7.5-FPS source rate. The property is not a sensor timestamp or a
  measurement of actual integration time. Driver delivery/pacing, USB capture,
  and other device timing remain to be isolated. Exact values are recorded in
  the diagnostic JSON; any persistent exposure change would require an
  explicitly approved test and must be reverted/documented.
  FFmpeg's read-only DirectShow mode listing advertises 352x288 YUYV/MJPEG and
  160x120 YUYV/MJPEG at 30 FPS (1280x720 MJPEG at 30 FPS, YUYV at 10 FPS).
  A 20-second YUYV passthrough at 160x120 still delivered only 150 frames
  (7.5 FPS, FFmpeg speed 0.989x), so reducing resolution alone did not remove
  the bottleneck. Matching low rates across raw/compressed outputs and both
  tested resolutions place the loss before encoding, but do not isolate whether
  DirectShow pacing, device delivery, USB/host scheduling, or camera state is
  responsible. The extra capture is recorded in the diagnostic JSON.
  A paired-condition follow-up also compared DirectShow device timestamps with
  FFmpeg wall-clock timestamps in separate 10-second 352x288 MJPEG decode runs.
  Both sessions delivered 75 frames (7.5 FPS, speed 0.975x), so changing the
  timestamp source did not restore frame delivery. Since these were sequential
  sessions, this is evidence against a timestamp-only reporting artifact, not
  a controlled simultaneous device-timing experiment.

### Camera FPS evidence correction

The later raw-H.264 comparison supersedes the immediately preceding
capture-diagnostic interpretation: default synchronization emitted 600 output
frames from 150 source frames in 20 seconds and FFmpeg reported 450 duplicates;
`-fps_mode passthrough` emitted 150 with no duplication. Corrected camera E2E
run 24 recorded 450/450 frames at 7.608 active FPS with no chunk drops. Strict
decode, correct-key extraction, Groth16 verification, and negative key/message
checks passed, but the result fails 30-FPS acquisition. Loopback NAL p50/p95 was
1.9672/147.3311 ms; payload patch p50/p95 was 7.3922/9.8505 ms. This is a host
camera result, not edge acceptance. All pre-run-24 ~30-FPS E2E counts used the
default raw-H.264 CFR synchronization path and cannot be treated as camera
acquisition FPS; those append-only records have not been rewritten. New camera
records require `fps_mode: passthrough`.

An isolated chunk-size experiment is recorded separately at
`benchmark/results/realtime_camera_chunk16k_experiment_20260924.json`. Its
60-second camera run (run 1 in that artifact) passed all E2E gates after fixing
the recorder's flow bound to account for one just-written input chunk above
the stream high-water mark. With 16 KiB pipe reads, it measured 1,801 frames at
30.002 active FPS, zero drops, and NAL pipe-to-TestClient p50/p95
2.2803/77.1584 ms; native patch p50/p95 was 71.2413/75.0032 ms. The baseline
run 21 used 1 KiB reads and reported 2.2267/125.257 ms for NAL p50/p95, but
these are separate live scenes and not a paired controlled experiment. This
suggests smaller-message overhead may contribute, but does not establish
causation. The p95 remains high and the transport remains in-process TestClient.

### Capture backend follow-up

`benchmark/results/realtime_camera_backend_comparison_20260924.json` records
additional temporary host capture probes (persistent camera controls were not
changed). DirectShow/FFmpeg MJPEG passthrough emitted
75 frames in about 10.15 seconds at each of 320x240, 640x480 and 1280x720
(about 7.4 wall FPS), so changing the requested mode did not recover 30 FPS.
OpenCV 4.12 Media Foundation capture returned 1,654 frames in 60.101 seconds
at 640x480 (27.5203 FPS), and 1,657 frames in 60.102 seconds at the requested
352x288 mode (27.5698 FPS). An additional 10-second 352x288 attempt that
requested 30 FPS explicitly reported 30 FPS but returned only 286 frames
(28.4549 wall FPS); OpenCV rejected the requested MJPEG FourCC and one-frame
buffer settings. Thus a Windows capture backend change removes most of the
DirectShow shortfall, but still misses the 30-FPS gate. These were
capture-only probes: no frame-drop counter, encoder, native stego processing,
HTTP channel, strict decoder, or edge target was involved. They do not prove
the camera sensor's actual exposure cadence.

A timestamp follow-up at 352x288 measured OpenCV `read()` completion
inter-arrival p50/p95 of 2.368/136.991 ms over 10 seconds and 2.526/137.901 ms
over 60 seconds (maximum 162.305 ms); 447 of 1,656 60-second intervals were
over 50 ms. In the 10-second probe, `CAP_PROP_POS_MSEC` advanced by a consistent
33.333 ms between returned samples, but that clock was not independently
validated as sensor time. The returned wall-time delivery was bursty. The
cause (camera/driver buffering, callback scheduling, or timestamp semantics)
remains unresolved; these measurements are not sensor-to-output latency.

An active-window follow-up counted 1,663 frames between the first successful
read and loop end in 59.674 seconds (27.868 active FPS); the loop exceeded its
60-second deadline while the last `read()` returned. Inter-arrival p50/p95/max
was 2.336/138.782/174.415 ms. This supersedes the earlier 27.5203/27.5698
capture-loop wall-rate figures as the comparable active rate; it still fails
the 30-FPS requirement and does not demonstrate a complete encoder/stego path.
A 60-second `CAPTURE.grab()`-only follow-up counted 1,786 successful grabs in
59.668 seconds from first grab to loop end (29.9327 grabs/active-second) with
141.377 ms p95 return interval; it skips retrieve/pixel conversion and remains
below 30 FPS. The 30-second probe similarly counted 887 grabs (29.5102 wall
FPS). These unpaired capture-only results suggest image retrieval/conversion
may contribute to throughput but do not establish causation or pass the gate.

## Remaining work to satisfy the whole goal

1. **Pin the edge target.** Record board/SoC, OS/kernel, compiler, OpenSSL,
   available camera interface and H.264 encoder. The current USB UVC camera
   emits MJPEG/YUYV; host runs use FFmpeg/libx264 software encoding, not an
   onboard hardware H.264 encoder.
2. **Run on that target.** Build and run the existing CTest, native fixture
   E2E, and physical camera WebSocket proof E2E there. Verify strict decoding
   with the intended software/hardware decoder, correct/wrong key behavior,
   frame accounting, and zero drops.
3. **Gate realtime on measured target results.** Capture at the deployment
   resolution/FPS for at least a 60-second soak; record warm/cold startup,
   arrival and end-to-end latency p50/p95, native patch latency p50/p95,
   queue depth/drops, capacity, decoded PSNR/SSIM, CPU, RSS, temperature and
   decoder validity. The manifest now makes the active acquisition gate
   explicit at 30 source frames/s (matching the requested capture mode, with
   no CFR-generated duplicates); the end-to-end p95 latency budget remains a
   deployment requirement to set for the chosen device.
4. **Close deployment-specific gaps.** Confirm that its camera profile fits
   the locked parser contract; configure the hardware encoder accordingly or
   reject the profile. Copy `doc/edge_deployment_manifest.template.yaml` to a
   target-specific manifest and fill it using the measured binary/settings and
   benchmark artifact. Do not substitute the standalone Python scheduler
   tests for the camera WebSocket path.

Until the target is identified and those measurements pass its declared
budget, report the system as functionally verified on fixtures and the current
development host only. Do not label it edge-ready or production-ready.

## Security and proof limits

- The embedded native frame is HMAC-authenticated and wrong-key extraction is
  rejected. It is not encrypted and currently has no sequence number, nonce,
  or replay protection.
- The Groth16 proof is generated for the message/key public-signal relation and
  verified after extraction. It does not prove the message describes the video,
  that the video came from a particular camera, or that every video bit is
  authentic. A proof-of-video claim would need a defined video commitment and
  circuit/verifier binding it into the public statement.
- A copied offline private key cannot be forced to expire by the video data
  plane alone. Expiration requires online authorization/revocation, trusted
  time, or secure hardware key custody.
- Strict FFmpeg `-v error -xerror` acceptance is required; ordinary FFmpeg
  success is insufficient. A software decoder pass does not guarantee a
  particular hardware decoder accepts every output.
- The Python `Blind-Core` analysis branch is distinct from the implemented
  native authenticated CAVLC blind extractor. Generic Python public-API
  embedding and generic H.264 profiles are not part of this native data-plane
  evidence.
