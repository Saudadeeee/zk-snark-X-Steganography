# Delivery benchmark protocol

This protocol reports the full delivery surface without mixing measured facts
with estimates. The benchmark data already committed in `results/` is the
quality, security, proof and timing baseline; `resource_benchmark.py` records
whole-process resource use for the same reproducible section set.

## Metrics and evidence

| Dimension | Metric | Source / command |
|---|---|---|
| Stego quality | full-video PSNR, minimum modified-frame PSNR, average SSIM, decoded proof/message match | `SEC1`, `sec1_quality_data.json` |
| Capacity | raw, patchable, validated and operating bits (kept separate) | `SEC2`, `sec2_capacity_data.json` |
| Detectability | chi-square, SPA and RS at the locked operating point | `SEC4`, `sec4_security_data.json` |
| ZKP | real Groth16 proof size and prove/verify latency | `SEC5`, `sec5_zkp_data.json` |
| Latency | one-time preprocessing, operational stages and end-to-end time | `SEC6`, `sec6_performance_data.json` |
| Resources | wall-clock, aggregate process-tree CPU seconds and peak RSS | `resource_benchmark.py` |

Run from the repository root after installing `requirements.lock` and the
documented Node/circom/ffmpeg toolchain:

```powershell
py -3.12 -m benchmark.resource_benchmark --sections 1 2 3 4 5 6 --timeout 180
```

For a faster smoke benchmark (not publication evidence):

```powershell
py -3.12 -m benchmark.resource_benchmark --sections 1 2 3 4 5 6 --timeout 180 --fast
```

The command writes the machine-specific resource result to the ignored
`benchmark/results/resource_benchmark.json`; retain that file with the source
commit, input-video hashes and tool versions when comparing machines. A zero
exit code from the underlying safe runner means each requested section passed
its schema and artifact validation.

## Current checked baseline

The checked `akiyo_q22_g1` artifacts record 53.01 dB full-video PSNR, 40.30 dB
minimum modified-frame PSNR, 0.999686 average SSIM, a verified 1232-bit
payload, 147-byte Groth16 proof-bearing payload, 1556.58 ms prove time, 8.5 ms
standalone verify time, and 85.03 s end-to-end SEC6 time. These are not claims
about another input video, host, codec configuration or load condition.
