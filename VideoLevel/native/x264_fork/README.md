# Direct-CAVLC x264 Fork

`zkstego-direct-cavlc.patch` applies to x264 commit
`0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`.

It embeds directly in quantized 4x4 luma residual coefficients, before inverse
transform/reconstruction and before CAVLC serialization. Consequently the
encoder's reconstructed reference frames match the decoder's; it is not an
Annex-B/SEI post-processing trick.

The payload bytes assigned to `x264_param_t.zkstego_payload` must remain valid
until `x264_encoder_close`. The fork is intentionally constrained to
Baseline/CAVLC, progressive 4x4 transform, one encoder thread, and one bit per
macroblock. It does not support CABAC, lossless, interlaced, 8x8 transform, or
changing the payload while an encoder is live.

Apply and build with an x264 checkout:

```bash
git checkout 0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee
git apply --unidiff-zero /path/to/zkstego-direct-cavlc.patch
./configure --disable-asm --enable-static
make -j2
```

The patch itself was compiled against that commit on the project Windows/UCRT64
toolchain with static, 8- and 10-bit x264 builds. It is a narrow initial fork:
before production use, add an end-to-end encode/decode/extract fixture and a
payload update API that safely crosses the x264 API dispatcher.

x264 is GPL-2.0-or-later unless separately commercially licensed. Distribution
of a binary that links this modified fork must comply with the applicable x264
licence terms.
