# Native in-band H.264 pipeline matrix

> Superseded: this first matrix used an incorrectly shared FFmpeg filter pad,
> which made SSIM falsely print `1.000000` throughout. The corrected graph
> explicitly splits reference/stego streams per metric. Use the corrected
> 2026-09-30 report generated after 14:28 UTC; do not cite these SSIM values.

Generated: 2026-09-30T13:54:25.650498+00:00

## Measurement host

- OS/runtime: Windows-11-10.0.26100-SP0 / Python 3.12.10
- CPU identifier: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel
- CPU cores: 14 physical / 20 logical
- Installed RAM: 23.63 GiB

> Transport benchmark only. A successful payload round-trip does not
> prove that the payload is a valid lattice-ZK proof or that the target
> application relation has been implemented.

| Case | Input | Duration (s) | Frames | Encode (s) | Encode (fps) | CPU (s) | Peak RSS (MiB) | Result | Embedded bits | Blind extract (s) | PSNR (dB) | SSIM |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| akiyo_cif_original | 352x288 | 10.010 | 300 | 1.214 | 247.062 | 1.125 | 6.754 | success | 120 | 1.047 | 45.132 | 1.000000 |
| akiyo_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.425 | 706.305 | 0.391 | 5.758 | success | 120 | 0.879 | 45.075 | 1.000000 |
| akiyo_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 3.452 | 86.911 | 3.328 | 11.074 | success | 120 | 1.864 | 46.607 | 1.000000 |
| city_cif_original | 352x288 | 10.000 | 300 | 2.908 | 103.150 | 2.812 | 6.785 | success | 120 | 2.098 | 37.435 | 1.000000 |
| city_cif_scaled_176x144 | 176x144 | 10.000 | 300 | 1.127 | 266.153 | 0.969 | 5.766 | success | 120 | 1.327 | 37.822 | 1.000000 |
| city_cif_scaled_704x576 | 704x576 | 10.000 | 300 | 7.337 | 40.890 | 6.938 | 11.113 | success | 120 | 4.389 | 39.692 | 1.000000 |
| coastguard_cif_original | 352x288 | 10.010 | 300 | 2.894 | 103.674 | 2.828 | 6.789 | success | 120 | 2.175 | 36.862 | 1.000000 |
| coastguard_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 1.037 | 289.241 | 0.953 | 5.770 | success | 120 | 1.148 | 38.077 | 1.000000 |
| coastguard_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 8.548 | 35.096 | 7.844 | 11.082 | success | 120 | 6.664 | 38.199 | 1.000000 |
| container_cif_original | 352x288 | 10.010 | 300 | 1.898 | 158.097 | 1.828 | 6.766 | success | 120 | 1.389 | 40.826 | 1.000000 |
| container_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.646 | 464.204 | 0.609 | 5.766 | success | 120 | 0.840 | 42.390 | 1.000000 |
| container_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 5.287 | 56.744 | 5.078 | 11.051 | success | 120 | 3.020 | 42.052 | 1.000000 |
| deadline_cif_original | 352x288 | 45.846 | 1374 | 10.045 | 136.785 | 9.531 | 6.773 | success | 120 | 4.665 | 41.670 | 1.000000 |
| deadline_cif_scaled_176x144 | 176x144 | 45.846 | 1374 | 2.503 | 548.992 | 2.375 | 5.766 | success | 120 | 1.642 | 41.948 | 1.000000 |
| deadline_cif_scaled_704x576 | 704x576 | 45.846 | 1374 | 27.143 | 50.621 | 26.203 | 11.066 | success | 120 | 12.913 | 42.899 | 1.000000 |
| football_cif_original | 352x288 | 8.667 | 260 | 2.697 | 96.415 | 2.484 | 6.781 | success | 120 | 2.155 | 36.235 | 1.000000 |
| football_cif_scaled_176x144 | 176x144 | 8.667 | 260 | 0.907 | 286.636 | 0.875 | 5.766 | success | 120 | 1.359 | 35.287 | 1.000000 |
| football_cif_scaled_704x576 | 704x576 | 8.667 | 260 | 7.904 | 32.895 | 7.609 | 11.184 | success | 120 | 5.998 | 38.565 | 1.000000 |
| foreman_cif_300f_original | 352x288 | 30.000 | 300 | 1.474 | 203.509 | 1.375 | 6.754 | success | 120 | 1.699 | 52.373 | 1.000000 |
| foreman_cif_300f_scaled_176x144 | 176x144 | 30.000 | 300 | 0.729 | 411.727 | 0.641 | 5.582 | success | 120 | 1.079 | 47.788 | 1.000000 |
| foreman_cif_300f_scaled_704x576 | 704x576 | 30.000 | 300 | 5.037 | 59.559 | 4.766 | 10.582 | success | 120 | 3.390 | 52.061 | 1.000000 |
| hall_monitor_cif_original | 352x288 | 10.010 | 300 | 1.711 | 175.382 | 1.609 | 6.770 | success | 120 | 1.417 | 40.012 | 1.000000 |
| hall_monitor_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.524 | 572.985 | 0.484 | 5.758 | success | 120 | 0.888 | 40.713 | 1.000000 |
| hall_monitor_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 7.160 | 41.900 | 6.891 | 11.035 | success | 120 | 4.382 | 41.549 | 1.000000 |

PSNR and SSIM are arithmetic means over frame-matched FFmpeg per-frame
logs; each case folder also retains `frame_quality.json` and raw metric
logs. Capacity failures are reported as failures and have no quality
score because the encoder does not publish a partial H.264 file.
PSNR is the per-frame arithmetic mean; SSIM is shown at FFmpeg's
six-decimal log precision, so `1.000000` is not evidence of exact
pixel equality (consult PSNR and per-frame logs). RSS and CPU are
sampled over the child process tree. Encode fps is frames / wall time.
These are offline desktop measurements, not end-to-end proof latency
or evidence of edge-device real-time operation.

## Method and interpretation

- Host CPU model reported by Windows WMI: 12th Gen Intel Core i7-12700H
  (14 physical cores / 20 logical processors); 23.63 GiB visible RAM.
- Native encoder build: pinned x264 fork `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`,
  GCC 15.2/UCRT64, static 8-bit, assembly disabled, CRF 23. The resulting
  executable SHA-256 is recorded in `summary.json`.
- Eight source clips were tested at their original 352x288 resolution. Each
  was also decoded and rescaled by FFmpeg/Lanczos into 176x144 and 704x576
  YUV420; these are derived variants, not native-resolution camera material.
- Application payload was one byte (`a5`), wrapped by the system's canonical
  14-byte `ZKVP` envelope and embedded as 120 in-band bits. This tests transport
  and blind extraction only; it is not a lattice-ZK proof.
- Quality compares decoded stego H.264 against the Y4M cover. It therefore
  includes both lossy H.264 coding and embedding effects; it does not isolate
  embedding-only distortion against a matched no-payload encode.
- Frame-level PSNR/SSIM, raw FFmpeg logs and H.264 outputs are retained in this
  local result directory. The aggregate report is tracked; generated media and
  per-frame files are not committed to keep the repository lean.

All 24 matrix cases encoded, blind-extracted the original byte, and yielded
frame-matched quality measurements for every frame. Across cases, PSNR ranged
from 35.287 to 52.373 dB; the lowest frame-level mean was high-motion Football
scaled to 176x144. FFmpeg prints SSIM to six decimal places, and every mean
rounded to `1.000000`; this is too coarse to claim pixel identity. The PSNR
values confirm nonzero distortion.

The largest measured case (Deadline, 704x576, 1,374 frames / 45.846 seconds)
took 27.143 seconds to encode and 12.913 seconds for the Python blind
extractor, excluding proof generation and API/session verification. The
combined batch time is close to the clip duration on this laptop, but that is
not a real-time streaming measurement. At Football 704x576, encode throughput
was only 32.895 frames/s and blind extraction took 5.998 seconds for an
8.667-second clip. No edge hardware was measured.

Re-run from the repository root with:

```powershell
python -m benchmark.native_pipeline_matrix `
  data/raw/akiyo_cif.y4m data/raw/city_cif.y4m `
  data/raw/coastguard_cif.y4m data/raw/container_cif.y4m `
  data/raw/deadline_cif.y4m data/raw/football_cif.y4m `
  data/raw/foreman_cif_300f.y4m data/raw/hall_monitor_cif.y4m `
  --encoder <path-to-zkstego_x264_y4m.exe> `
  --scale 176x144 --scale 704x576
```
