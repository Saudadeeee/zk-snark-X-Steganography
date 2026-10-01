# ISW21 experimental full-envelope transport through H.264 CAVLC (2026-10-01)

## Result and scope

One real 704x576 H.264 Constrained Baseline clip carried the entire 23,907-byte
experimental ISW21 statement/response envelope in quantized residual
coefficients. The blind extractor recovered those bytes exactly from the
received video; a separate Linux verifier process accepted the recovered
proof with the expected context and rejected it with another expected context.
The final verifier took the extractor's output, not the prover's proof file.
No proof sidecar was supplied to the extractor.

This is an application-shaped **toy** relation. The commitment uses a 19-bit
modulus without a concrete SIS security estimate; the 32-byte context in this
trial is a fixed fixture, not a digest of a verifier session or the normalized
video. The result establishes transport and separate-process proof verification
for this one profile; it does not establish the target security relation,
tamper/replay/expiry policy, production readiness, or realtime operation.

## Reproducible inputs

| Item | Value |
| --- | --- |
| Source | `benchmark/results/native_pipeline_matrix_20260930T142913Z/prepared/deadline_cif_704x576.y4m` |
| Source dimensions and duration | 704x576, 1,374 frames, 45.846 s; Lanczos-scaled from Deadline CIF |
| Source size / SHA-256 | 835,752,056 bytes / `78b6a7c0ca6f22547caecc06e2196136409eaeca0beb8d47bc0ba531c753cd50` |
| ISW21 upstream | `48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e`, with tracked RNG and QAP-prefix research patches |
| x264 upstream | `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`, with `native/x264_fork/zkstego-direct-cavlc.patch` |
| Encoder | GCC 13.3, static x264 8-bit/4:2:0, assembly disabled, native adapter defaults (`ultrafast`, `zerolatency`, CRF 23, one thread, IDR while payload remains) |
| Proof envelope | 23,907 bytes, SHA-256 `e2dc5fe5b8076c93184fc4fe70c2a8ea54e8624511bbba0ce5505907171f5d45` |
| In-band `ZKVP` framing | 14-byte version/kind/length/CRC32 header; 23,921 bytes / 191,368 bits total |
| Designated verifier key | 2,419,872 bytes, POSIX mode `0600`; kept outside the video and private to the verifier |

The video/proof experiment ran in an Ubuntu 24.04 x86-64 Docker container on
an Intel Core i7-12700H host. The blind extractor ran with Python 3.12 on
Windows 11. The code under test was the current worktree on 2026-10-01;
these measurements are one run, not a timing distribution.

## Measured path

| Stage | Observed result |
| --- | ---: |
| Native encode | Success; 191,368 / 191,368 carrier bits committed |
| Native encoder wall time | 43.90 s (`/usr/bin/time`) |
| Native encoder maximum RSS | 9,920 KiB (`/usr/bin/time`) |
| H.264 output | 31,537,995 bytes; SHA-256 `e9b0edbef04604b0367c185b950fd863c7f6bdd7fe988403bff497bf5e0bc212` |
| ffprobe | H.264 Constrained Baseline, 704x576, 1,374 decoded frames |
| Parsed NALs | 1,304 IDR, 70 P slices, 1,304 SPS, 1,304 PPS, 1,374 AUD; 0 SEI |
| Blind extraction | 23,907 bytes, SHA-256 identical to prover envelope; exact byte match |
| Blind extraction wall time | 1,819.342 s (Python `perf_counter`) |
| Blind extraction RAM | Largest manually sampled working set 101,982,208 bytes (~97.3 MiB); **not** a measured peak |
| Separate verifier, expected context | `SEPARATE_PROCESS_LATTICE_VERIFY=PASS`, exit 0 |
| Separate verifier process wall / max RSS | 0.04 s / 6,720 KiB (`/usr/bin/time`) |
| Same extracted proof, wrong expected context | Rejected: `proof context does not match verifier session`, exit 22 |
| Per-frame quality vs Y4M source | 1,374 matched frames; mean PSNR 38.973894 dB; mean FFmpeg all-plane SSIM 0.964732 |

The frame metrics compare the encoded result to the Y4M source, so they include
normal lossy H.264 encoding as well as embedding. There is no matched
no-payload control for isolating the embedding-only distortion. The full
per-frame FFmpeg PSNR/SSIM logs and the 31.5 MB output were kept in the local
system temporary directory `zkstego-isw21-full-probe-20261001`, outside this
repository, to avoid adding bulky generated data to Git. Temporary artifacts
may be removed by the operating system.

The measured extraction was about 39.7 times the clip duration; therefore
this tested Python blind-extraction path is not realtime. The 43.90-second
encoder number is an offline, one-run value on the stated desktop CPU and
does not establish edge-device performance. The verifier's 0.04-second
process time does not include video parsing or policy checks.

## Trust and implementation gaps exposed by this trial

The smoke proof's public context is the fixed 32-byte fixture
`913ae120775802b46ca91108d2334f8029f163059a4418ce7d26b0520f8bd731`.
The verifier now requires an independently supplied expected context and can
reject a cross-context proof, but no session challenge, expiry, one-use record,
registry policy, or normalized-video digest is bound in this video. Replaying
the same valid proof in the same expected context remains possible. CRC32 in
the `ZKVP` transport header is an error check, not authentication.

The target relation draft uses a sign-only trailing-one carrier profile,
whereas this native encoder uses magnitude parity of an eligible AC
coefficient with `abs(level) >= 5`. The normalized-video commitment and exact
carrier schedule must be redefined and tested for this native profile before
the proof can be said to bind the received H.264 video. The experiment also
required a long, scaled 704x576 clip: earlier 300-frame CIF tests could not
carry even the 21,331-byte response. This one success does not imply sufficient
capacity for other videos or live camera windows.

## Validation gates run

- ISW21 separate-process CTest: `1/1` passed in 22.20 s, including two
  contexts, wrong context, wrong setup key, malformed/truncated inputs, and
  response tampering.
- Native adapter CTest in a Linux virtual environment with `requirements.txt`
  installed: `7/7` passed in 8.75 s, including Y4M encode, blind extraction,
  and binary payload-file input. An initial run before installing Python
  dependencies had 3 import failures (`numpy` missing); no source bug was
  inferred from that environment failure.
- `ffprobe` counted 1,374 decoded video frames; FFmpeg matched 1,374 frames
  for PSNR and SSIM; a direct Annex-B parse found zero SEI NAL units.
