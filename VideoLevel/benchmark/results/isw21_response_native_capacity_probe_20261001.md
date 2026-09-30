# ISW21 response bytes through the native CAVLC encoder (2026-10-01)

## Purpose and scope

This probe takes the response bytes emitted by the pinned-upstream ISW21
application-shaped smoke test and passes those exact bytes to the project's
patched x264 direct-CAVLC encoder. It measures whether the current native
IDR-only carrier can transport the response on a real Y4M source. It does not
prove the target application relation: the smoke circuit uses insecure toy
parameters, and only its response is carried (not its public statement,
session context, framing, or verifier key).

## Inputs and configuration

- Cover: `data/raw/akiyo_cif.y4m`, 300 frames, 352x288, progressive 4:2:0,
  30000/1001 fps (~10.01 s).
- Proof source: `research/isw21_r1cs_opening_smoke`, pinned upstream ISW21
  revision `48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e`, profile `B19C20`.
- Blob: 21,331-byte canonical fixed-width proof response only; SHA-256
  `1941e7e7b27d31dbddd942a775abc9b67ce17cb4f958000c924ab41ede48f117`.
- Encoder: clean x264 checkout at
  `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`, current repository patch,
  UCRT64 GCC, static 8-bit library, assembly disabled. The adapter uses
  `ultrafast`/`zerolatency`, Baseline/CAVLC, one thread, CRF 23, and IDR-only
  carrier mode.

The proof smoke test passed its honest verification and response
serialize/decode/verify checks before writing the blob. It also rejected a
modified response and malformed encodings. Its warning remains applicable:
the commitment modulus is only 19 bits and the opening only 16 bits; this is
not a secure production proof.

## Result

| Metric | Observed |
|---|---:|
| Response file requested | 21,331 bytes / 170,648 physical bits |
| Bits committed before exhaustion | 10,426 bits (1,303.25-byte equivalent) |
| Requested bits committed | 6.11% |
| Capacity shortfall | response needs 16.37x this run's committed bits |
| Frames read/encoded before fail-closed return | 300 |
| x264 frame summary | 300 I frames, 0 P frames |
| x264 reported average QP | 28.97 |
| x264 reported bitrate before abort | 1,325.60 kb/s |
| Process wall time (PowerShell `Measure-Command`, one run) | 1.784 s |
| Peak RAM | Not measured |
| Final H.264 published | No |
| PSNR / SSIM | Not applicable; no complete output was published |

The encoder returned non-zero with `payload capacity insufficient: embedded
10426 of 170648 bits`. Its temporary partial stream was removed; the requested
output path did not exist after the run. Because the 14-byte blind framing
header and statement are not in this test blob, a complete envelope would need
more than the measured response bits.

## Interpretation

This is direct evidence that the current 300-frame IDR-only native operating
point cannot carry even the 21.3 kB ISW21 response encoding. A linear
extrapolation from 10,426 committed bits per 300 frames suggests around 4,900
similar frames (about 164 seconds at the same frame rate) just for the raw
response; this is a planning estimate, not a capacity guarantee. Content,
resolution, QP, payload bit pattern, and CAVLC overflow retries all affect the
real carrier count. Forcing every frame to I while the payload is outstanding
also changes coding cost; this failed run is not a quality or realtime
benchmark.

## Follow-up: longer clip and higher resolution

To test whether the 300-frame Akiyo result was only a short-clip limitation, a
fresh proof was generated with the same toy smoke circuit. Its response is
still exactly 21,331 bytes, but is randomized and has a different SHA-256 from
the earlier proof used above:

```text
response SHA-256: C2D336F678DC1F5803C536508DBA90EBAB1296093B89A0A66F5958819C346D10
```

The cover was `data/raw/deadline_cif.y4m`, 1,374 frames / 45.846 seconds at
352x288 and 30000/1001 fps. The 704x576 cover was an existing Lanczos-scaled
YUV420 derivative of that same clip. These are offline native-encoder runs,
using the patched x264 build noted above, CRF 23 and the current IDR-only
carrier policy (P frames are allowed only after the payload is complete).

| Cover / payload | Result | Carrier and encoder observations |
|---|---|---|
| 352x288 / 21,331-byte raw response | Fail closed | 116,001 / 170,648 bits (67.95%); 1,374 I, 0 P; 18.017 s; no output published |
| 704x576 / 21,331-byte raw response | Success | 1,164 I, 210 P; 41.924 s; output published |
| 704x576 / 21,345-byte `ZKVP` envelope | Success | 14-byte version/kind/length/CRC32 header plus response; 1,164 I, 210 P; 41.680 s; output size 29,361,432 bytes |

The successful framed run's x264 log reported average QP 29.94 for I frames,
23.47 for P frames, and 5,123.51 kb/s. FFmpeg compared all 1,374 decoded
frames with the scaled Y4M cover: aggregate PSNR average 39.192754 dB and SSIM
All 0.966513. These include ordinary lossy H.264 coding as well as embedding;
they do not isolate embedding-only distortion. Peak encoder RAM was not
measured.

The project blind extractor was then run on that H.264 file, with no proof
sidecar. It validated the `ZKVP` header, exact length and CRC32, and returned
the exact 21,331 response bytes:

```text
BLIND_ZKVP_RESPONSE_BYTES=21331
BLIND_ZKVP_RESPONSE_ROUNDTRIP=PASS
```

The extraction process consumed at least 1,117.2 CPU seconds at the last live
process sample and completed in the next 7.45-second polling interval; an exact
wall stopwatch was not attached. Sampled working set peaked at 95.8 MiB. This
is a successful blind transport round-trip, but decisively not a realtime
measurement: verification-side extraction alone took many minutes for a
45.846-second clip. The 14-byte envelope contains no public application
statement, video/session binding, expiry data, or complete proof format. The
only relation remains the deliberately insecure smoke relation described
above.

### Parser cost diagnostic

A separate cProfile run on the existing 704x576 Deadline matrix output (the
small-payload benchmark carrier, not the proof-sized output) parsed its NAL
stream in 10.520 seconds, then parsed one trusted IDR's CAVLC in 4.361 seconds
for 1,584 macroblocks. The profile recorded 3,528,124 calls; the largest
cumulative costs were `TraceableCAVLCParser.extract_with_offsets` (4.355 s),
`decode_block_cavlc` (3.414 s across 33,069 calls), and `decode_vlc` (1.536 s
across 80,813 calls). This is a hotspot diagnostic from a different encoded
stream, not a per-frame estimate for the proof video, but it points to Python
CAVLC block/VLC decoding—not ZK verification—as the first extraction bottleneck
to optimize.

The 704x576 run demonstrates that a larger carrier can transport the response
and the current 14-byte framing; it does not make the 352x288 profile
sufficient or prove a general capacity bound. The next gates are a versioned
statement/session envelope, secure application relation and key lifecycle,
capacity/quality trials on the intended cover profile, and a faster trusted
blind parser. P-slice carrier capacity is still not counted because the
general P-slice blind parser path is not established as trusted.
