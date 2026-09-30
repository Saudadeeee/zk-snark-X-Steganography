# Native in-band H.264 pipeline matrix

Generated: 2026-09-30T14:32:53.571621+00:00

## Measurement host

- OS/runtime: Windows-11-10.0.26100-SP0 / Python 3.12.10
- CPU identifier: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel
- CPU cores: 14 physical / 20 logical
- Installed RAM: 23.63 GiB
- Metric libraries: NumPy 2.2.6; scikit-image 0.26.0

> Transport benchmark only. A successful payload round-trip does not
> prove that the payload is a valid lattice-ZK proof or that the target
> application relation has been implemented.

| Case | Input | Duration (s) | Frames | Encode (s) | Encode (fps) | Encode CPU (s) | Encode RSS (MiB) | Result | Embedded bits | Blind test | Extract (s) | Extract CPU (s) | Extract peak RSS (MiB) | PSNR (dB) | FFmpeg SSIM all (6dp) | Luma SSIM (precise) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| akiyo_cif_original | 352x288 | 10.010 | 300 | 1.424 | 210.677 | 1.281 | 6.812 | success | 120 | PASS | 1.262 | 1.109 | 42.305 | 45.132 | 0.984705 | - |
| akiyo_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.491 | 611.533 | 0.375 | 5.758 | success | 120 | PASS | 1.058 | 0.906 | 37.461 | 45.075 | 0.988528 | - |
| akiyo_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 4.126 | 72.710 | 3.922 | 11.070 | success | 120 | PASS | 2.392 | 2.219 | 53.359 | 46.607 | 0.986753 | - |
| city_cif_original | 352x288 | 10.000 | 300 | 3.434 | 87.374 | 3.219 | 6.785 | success | 120 | PASS | 2.592 | 2.172 | 42.762 | 37.435 | 0.955092 | - |
| city_cif_scaled_176x144 | 176x144 | 10.000 | 300 | 1.234 | 243.042 | 1.078 | 5.766 | success | 120 | PASS | 1.648 | 1.391 | 38.457 | 37.822 | 0.960522 | - |
| city_cif_scaled_704x576 | 704x576 | 10.000 | 300 | 8.224 | 36.480 | 7.609 | 11.094 | success | 120 | PASS | 5.652 | 5.156 | 58.457 | 39.692 | 0.964836 | - |
| coastguard_cif_original | 352x288 | 10.010 | 300 | 3.438 | 87.272 | 3.172 | 6.781 | success | 120 | PASS | 2.708 | 2.359 | 42.992 | 36.862 | 0.951341 | - |
| coastguard_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 1.221 | 245.780 | 1.109 | 5.766 | success | 120 | PASS | 1.537 | 1.203 | 38.562 | 38.077 | 0.961440 | - |
| coastguard_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 9.474 | 31.666 | 8.875 | 11.066 | success | 120 | PASS | 8.059 | 7.344 | 60.305 | 38.199 | 0.955946 | - |
| container_cif_original | 352x288 | 10.010 | 300 | 2.154 | 139.293 | 1.922 | 6.832 | success | 120 | PASS | 1.806 | 1.562 | 41.164 | 40.826 | 0.963631 | - |
| container_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.786 | 381.786 | 0.688 | 5.766 | success | 120 | PASS | 1.082 | 0.906 | 37.625 | 42.390 | 0.974684 | - |
| container_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 5.972 | 50.232 | 5.500 | 11.059 | success | 120 | PASS | 3.769 | 3.406 | 56.613 | 42.052 | 0.970217 | - |
| deadline_cif_original | 352x288 | 45.846 | 1374 | 10.462 | 131.327 | 9.844 | 6.836 | success | 120 | PASS | 5.816 | 5.484 | 47.039 | 41.670 | 0.980937 | - |
| deadline_cif_scaled_176x144 | 176x144 | 45.846 | 1374 | 2.824 | 486.613 | 2.578 | 5.820 | success | 120 | PASS | 1.968 | 1.797 | 39.781 | 41.948 | 0.984230 | - |
| deadline_cif_scaled_704x576 | 704x576 | 45.846 | 1374 | 28.584 | 48.069 | 26.391 | 11.062 | success | 120 | PASS | 13.439 | 12.766 | 64.273 | 42.899 | 0.981228 | - |
| football_cif_original | 352x288 | 8.667 | 260 | 2.475 | 105.069 | 2.125 | 6.797 | success | 120 | PASS | 2.323 | 2.062 | 42.160 | 36.235 | 0.927520 | - |
| football_cif_scaled_176x144 | 176x144 | 8.667 | 260 | 1.020 | 254.910 | 0.828 | 5.766 | success | 120 | PASS | 1.413 | 1.188 | 38.109 | 35.287 | 0.919812 | - |
| football_cif_scaled_704x576 | 704x576 | 8.667 | 260 | 8.046 | 32.315 | 7.531 | 11.203 | success | 120 | PASS | 6.825 | 6.438 | 59.078 | 38.565 | 0.945328 | - |
| foreman_cif_300f_original | 352x288 | 30.000 | 300 | 1.588 | 188.937 | 1.469 | 6.816 | success | 120 | PASS | 1.921 | 1.703 | 42.191 | 52.373 | 0.998721 | - |
| foreman_cif_300f_scaled_176x144 | 176x144 | 30.000 | 300 | 0.811 | 369.725 | 0.703 | 5.578 | success | 120 | PASS | 1.300 | 1.094 | 37.812 | 47.788 | 0.996170 | - |
| foreman_cif_300f_scaled_704x576 | 704x576 | 30.000 | 300 | 5.558 | 53.977 | 5.281 | 10.680 | success | 120 | PASS | 4.349 | 4.031 | 50.027 | 52.061 | 0.997889 | - |
| hall_monitor_cif_original | 352x288 | 10.010 | 300 | 1.965 | 152.685 | 1.797 | 6.766 | success | 120 | PASS | 1.611 | 1.344 | 41.328 | 40.012 | 0.952384 | - |
| hall_monitor_cif_scaled_176x144 | 176x144 | 10.010 | 300 | 0.577 | 519.576 | 0.469 | 5.820 | success | 120 | PASS | 0.989 | 0.781 | 37.445 | 40.713 | 0.966032 | - |
| hall_monitor_cif_scaled_704x576 | 704x576 | 10.010 | 300 | 7.487 | 40.070 | 7.062 | 11.027 | success | 120 | PASS | 4.810 | 4.297 | 57.660 | 41.549 | 0.960823 | - |

PSNR and FFmpeg's all-plane SSIM are per-frame FFmpeg measurements.
Optional luma SSIM is computed by scikit-image at full precision.
Each case retains
`frame_quality.json` and FFmpeg's raw metric
logs. Capacity failures are reported as failures and have no quality
score because the encoder does not publish a partial H.264 file.
FFmpeg all-plane SSIM has six-decimal precision and is preserved in
each frame row as `ssim_ffmpeg_all`; a reported `1.000000` means the
score rounded to that display precision, not exact pixel equality.
The optional luma SSIM is costly and is not enabled in the full matrix.
RSS and CPU are
sampled over the child process tree. Encode fps is frames / wall time.
These are offline desktop measurements, not end-to-end proof latency
or evidence of edge-device real-time operation.

## Method and interpretation

- Host CPU model from Windows WMI: 12th Gen Intel Core i7-12700H
  (14 physical / 20 logical cores), Windows 11, Python 3.12.10, 23.63 GiB RAM.
- Native encoder: pinned x264 fork `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`,
  GCC 15.2/UCRT64, static 8-bit build, assembly disabled, CRF 23. The H.264
  output is Constrained Baseline / CAVLC. The executable hash is in
  `summary.json`.
- The 8 source sequences are CIF (352x288), with 260 to 1,374 frames and
  8.667 to 45.846 seconds. Each source was also decoded and Lanczos-scaled by
  FFmpeg into 176x144 and 704x576; those 16 cases are derived-resolution
  variants, not native camera footage at those sizes.
- Each run embeds application byte `a5` inside the real 14-byte `ZKVP`
  blind-extraction envelope: 15 bytes / 120 carrier bits. These results prove
  only envelope transport and byte extraction, not proof embedding or ZK
  verification.
- FFmpeg PSNR and SSIM filters use explicitly split reference/stego inputs;
  the earlier report with all SSIM values `1.000000` was superseded because
  its filter graph reused pads incorrectly. Corrected SSIM is the arithmetic
  mean of per-frame all-plane FFmpeg SSIM. Per-frame PSNR/SSIM logs and JSON
  are retained in this result directory. Optional full-precision luma SSIM
  (`--precise-ssim`) was independently measured for the Akiyo CIF smoke case
  as 0.97757633, but omitted from the full matrix because that analysis is
  computationally expensive.
- Image quality is measured against the original Y4M cover, so PSNR/SSIM
  includes lossy CRF encoding as well as embedding. There is no matched
  no-payload encode here to isolate the incremental steganographic distortion.

Across all 24 cases, encode, blind byte extraction and frame counts passed.
The per-case mean PSNR spans 35.287–52.373 dB; corrected FFmpeg SSIM spans
0.919812–0.998721. Encoder throughput spans 31.666–611.533 frames/s, with
5.578–11.203 MiB sampled peak RSS. The Python blind extractor takes
0.989–14.271 seconds and 37.445–64.273 MiB peak RSS for the whole clip. The
slowest extractor is Deadline 704x576 (1,374 frames).

This is not a real-time system result: native encoding alone exceeds 30 fps
for this corpus on this laptop, but the least favorable 704x576 encode is only
31.666 fps, and blind extraction is a whole-video batch operation. The full
ZK prover/verifier, camera ingest, session-policy check and edge hardware are
not in this benchmark. Separately, the 33,803-byte experimental LNP22 artifact
(already known not to prove the target relation) fit only 10,420 of 270,424
requested bits in the 300-frame Akiyo capacity probe; that output was rejected
and no proof-sized video was published. Thus this 120-bit matrix does not
resolve target-proof capacity.

Native CTest: 7/7 passed. Focused runner tests: 12/12 passed; Ruff clean.
Neither result supplies the missing target relation or cryptographic proof.
