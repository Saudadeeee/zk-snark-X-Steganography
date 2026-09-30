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

The next carrier gate is to test longer/more-capable real clips and a validated
blind-stable profile, then measure a full versioned proof/session envelope.
P-slice capacity is not counted here because the current general P-slice blind
parser path is not established as trusted.
