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
The initial carrier hook covers I_4x4 macroblocks only, so capacity is at most
one bit per eligible I_4x4 macroblock, not one bit per every macroblock. The
blind-stable coordinate is luma block 15, AC scan position 15, with absolute
quantized level at least 5. On a parity mismatch the fork increases magnitude
by one, preserving the decoder's eligibility test. The API rejects CABAC,
lossless, interlaced, 8x8-transform, multi-threaded, and non-I420 payload
configurations. There is no payload update API; the supplied bytes must remain
valid and unchanged until the encoder is closed.

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
120 framed bits were committed. `tests/blind_extract_smoke.py` uses the repository CAVLC parser to
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
commit, built as static 8-bit x264 with GCC 15.2/UCRT64, and passed all four
native CTests in 1.50 s: the direct encoder smoke, adapter smoke, blind CAVLC
extraction, and the existing native live tests. The synthetic 256x256 I420
I-frame fixture emitted a 106,642-byte H.264 stream; the encoder reported 120
committed bits (a 14-byte framing header plus one payload byte), and extraction
derived the payload length from the video and recovered `a5`. This is a
synthetic smoke test, not a real-camera/video benchmark or a ZK proof E2E
result. It has no PSNR/SSIM or RAM measurement. Assembly optimizations were
disabled, so its timing must not be generalized to normal x264 builds.

The original x264 fork changes were compiled against the pinned commit on the
project Windows/UCRT64 toolchain. Full 8-/10-bit rebuild coverage and blind
extraction of self-delimiting arbitrary payloads are separate requirements;
passing these fixtures does not make the fork or end-to-end system
production-ready.

x264 is GPL-2.0-or-later unless separately commercially licensed. Distribution
of a binary that links this modified fork must comply with the applicable x264
licence terms.
