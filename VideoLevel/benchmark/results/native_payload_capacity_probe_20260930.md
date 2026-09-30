# Native H.264 payload capacity probe (2026-09-30)

## Purpose

Measure the current native pixel-level direct-CAVLC encoder with a real
serialized proof-sized artifact, without exceeding Windows command-line size
limits. This is a transport-capacity stress test only. The input proof artifact
is from the repository's experimental LNP22 probe, which prior security review
found does **not** prove the target payload-opening/video/session relation and
must not be presented as a valid target ZK proof.

## Inputs and command

- Cover: `data/raw/akiyo_cif.y4m`, 300 progressive YUV420 frames, 352x288,
  30000/1001 fps (~10.01 s).
- Stress payload: `benchmark/results/lnp22-video-e2e-widh37b4/proof.lnpf`,
  33,803 bytes, SHA-256
  `115318ac0f02e2e318d3e8ac892cf540f0eeca1ae785a3cf7b9fdd8566fbb574`.
- Encoder: native `zkstego_x264_y4m`, built against the pinned x264 fork at
  `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`, GCC 15.2/UCRT64, 8-bit static,
  assembly disabled; the adapter uses its current CRF 23 configuration.

The CLI read the binary payload using `--payload-file` and encoded the full
Y4M stream. It rejected publication when the payload did not fit. The observed
diagnostic was:

```text
payload capacity insufficient: embedded 10420 of 270424 bits
```

## Measured result

| Metric | Observed |
|---|---:|
| Payload requested | 270,424 bits (33,803 bytes) |
| Bits embedded before exhaustion | 10,420 bits (1,302.5-byte equivalent) |
| Fraction of requested bits | 3.85% |
| Frames encoded | 300 |
| x264 frame summary | 300 I frames, 0 P frames |
| Wall time | 3.029 s |
| Process CPU time | 1.906 s |
| Peak RAM | Not measured reliably in this run |
| Final H.264 published | No |

The repeated I frames are caused by forcing IDR pictures until all direct
payload bits have been committed. At this Akiyo/QP/profile point, the target
artifact would need substantially more video/capacity; the current 300-frame
input cannot carry it. A repeated run that requested a peak-working-set value
returned zero from the process handle, so that value is intentionally omitted
rather than reported as a measurement. The CLI removed the provisional partial
output on capacity failure; no incomplete final output was published.

## Interpretation and limits

This is one real stress measurement for one video, encoder configuration, and
non-target LNP22 artifact. It is not a universal H.264 capacity bound, not an
accepted proof, and not evidence of blind proof verification. The 10,420-bit
count is committed carrier capacity under the current IDR-only native profile;
it excludes any proof relation/security claim. It also demonstrates a serious
coding-efficiency tradeoff: when the payload cannot fit, all 300 frames are
forced to I pictures before the adapter aborts. No valid stego file existed,
so PSNR/SSIM for this failed stress attempt are not applicable. RAM collection
and broader multi-video/resolution/duration measurements remain open.
