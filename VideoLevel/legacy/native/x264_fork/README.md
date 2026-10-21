# Direct-CAVLC x264 Fork

`zkstego-direct-cavlc.patch` applies to x264 commit
`0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`.

It embeds directly in quantized 4x4 luma residual coefficients, before inverse
transform/reconstruction and before CAVLC serialization. Consequently the
encoder's reconstructed reference frames match the decoder's; it is not an
Annex-B/SEI post-processing trick.

The payload bytes assigned to `x264_param_t.zkstego_payload` must remain valid
until `x264_encoder_close`. A non-empty direct payload is accepted only with
I420, CAVLC, progressive 4x4 transform, one encoder thread, and no B frames.
The carrier hook covers I_4x4 macroblocks in I slices only, so capacity is at
most one bit per eligible I_4x4 macroblock, not one bit per every macroblock.
The blind-stable carrier is the first eligible coefficient found by ascending
luma 4x4 block order, then descending AC scan positions 15 through 1,
requiring absolute quantized level at least 5. x264 stores its quantized 4x4
coefficient buffer transposed; the fork maps scan positions through that
layout before modifying a coefficient. Trellis is enabled in direct-payload
mode so x264 quantizes every I4x4 block in the same order the blind parser
derives from the coded macroblock. On a parity mismatch the fork changes the
magnitude by one without crossing the eligibility threshold. The adapter
forces IDR pictures while payload bits remain, then returns to automatic GOP
selection after the envelope is complete. This lets extraction traverse only
IDR CAVLC slices and avoids relying on parser support for inter-predicted
macroblocks. It also increases bitrate while the payload is being embedded;
the impact needs broader quality and performance benchmarks. The API rejects CABAC,
lossless, interlaced, 8x8-transform, multi-threaded, and non-I420 payload
configurations. There is no payload update API; the supplied bytes must remain
valid and unchanged until the encoder is closed.
In direct-payload mode, the fork also suppresses x264's identification SEI in
both `x264_encoder_headers()` and the ordinary encode path. The native adapter
does not enable HRD or attach custom SEI; its emitted-stream smoke test rejects
every NAL unit of type 6. This means the proof/payload transport has no SEI
dependency and the tested adapter output has no SEI NALs at all.

Apply and build with an x264 checkout:

```bash
git checkout 0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee
git apply --unidiff-zero /path/to/zkstego-direct-cavlc.patch
./configure --disable-asm --enable-static
make -j2
```

The pinned fork now exposes `x264_encoder_zkstego_embedded_bits()` so callers
can distinguish requested bytes from bits committed after CAVLC overflow
retries. The API rejects negative sizes, non-empty null payloads, and payload
lengths above `INT_MAX / 8` before bit indexing can overflow. The adapter also
enforces that bound.

`tests/zkstego_x264_smoke.c` encodes a deterministic I420 frame, checks that
unsupported modes and oversized payloads are rejected, and asserts that all
120 framed bits were committed, and rejects every SEI NAL in the emitted
stream. A second fixture constrains x264 to I16x16
macroblocks and confirms those non-carrier blocks consume zero I4x4 payload
bits. `tests/blind_extract_smoke.py` uses the repository CAVLC parser to
rederive carrier coordinates from the emitted stream and recover the fixture
byte. `tests/zkstego_adapter_smoke.c` exercises the project's native encoder
adapter, including its count API, oversized-payload rejection, and a
capacity-failure case. Adapter users must call `zks_x264_encoder_finish()`;
it drains delayed frames and returns `ZKS_ERR_CAPACITY` unless every requested
payload bit was committed. Treat callback output as provisional and buffer it
to a temporary artifact until finish succeeds; discard it on any error. Finish
is idempotent, and encoding more frames afterward is rejected. The expected
payload is only a test assertion: the extractor recovers length from the
in-video framing header and checks its CRC. This establishes byte-payload
framing only; CRC-32 is not authentication, and the fixtures do not verify a
proof or measure quality. Reproduction from an applied fork checkout:

```bash
gcc -O2 -std=c11 -Wall -Wextra -Werror=implicit-function-declaration \
  -I. -o zkstego_x264_smoke \
  /path/to/VideoLevel/native/x264_fork/tests/zkstego_x264_smoke.c \
  ./libx264.a -lm -lpthread -lws2_32
./zkstego_x264_smoke smoke.h264
gcc -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror \
  -I/path/to/VideoLevel/native/include -I. \
  -o zkstego_adapter_smoke \
  /path/to/VideoLevel/native/x264_fork/tests/zkstego_adapter_smoke.c \
  /path/to/VideoLevel/native/src/x264_encoder.c \
  ./libx264.a -lm -lpthread -lws2_32
./zkstego_adapter_smoke
py -3.12 /path/to/VideoLevel/native/x264_fork/tests/blind_extract_smoke.py \
  smoke.h264 a5
```

On 2026-09-30, the exact patch applied to a clean checkout of the pinned x264
commit and built as static 8-bit x264 with GCC 15.2/UCRT64. With assembly
disabled, all six native CTests passed in 3.86 s, including both synthetic
blind extraction and real-Y4M encode/extract tests. A separate run encoded
`data/raw/akiyo_cif.y4m` (300 frames, 352x288) to a 718,868-byte constrained
Baseline H.264 stream. The adapter reported 120 embedded bits (the 14-byte
framing header plus one payload byte); blind extraction recovered `a5` from
the stream itself, `ffprobe` counted all 300 frames, and FFmpeg decoded the
output without errors. x264 reported 11 I frames and 289 P frames: repeated
IDRs were forced while the payload remained, which is a visible coding-cost
tradeoff and needs broad bitrate/quality/performance measurement. These runs
verify byte-payload transport only, not ZK proof E2E, and do not yet include
RAM measurement. An aligned, frame-by-frame FFmpeg comparison against the
source Y4M measured average PSNR 45.07 dB and SSIM 0.984705. These are whole
encode results, not an isolated measurement of the embedding distortion versus
the same encoder run without payload. Assembly optimizations were disabled, so
timing must not be generalized to normal x264 builds.

The original x264 fork changes were compiled against the pinned commit on the
project Windows/UCRT64 toolchain. Full 8-/10-bit rebuild coverage and blind
extraction of self-delimiting arbitrary payloads are separate requirements;
passing these fixtures does not make the fork or end-to-end system
production-ready.

x264 is GPL-2.0-or-later unless separately commercially licensed. Distribution
of a binary that links this modified fork must comply with the applicable x264
licence terms.
