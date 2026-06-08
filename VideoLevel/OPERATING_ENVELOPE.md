# Supported Operating Envelope

Last updated: 2026-06-08

This file defines the supported operating envelope for the current system.
Future robust watermarking, C2PA trust tiers, fingerprint registries, TEE, and
ZKML are not part of this baseline.

## Strongest Supported Regime

- Codec: H.264/AVC.
- Profile: baseline / constrained baseline.
- Entropy coding: CAVLC.
- GOP: GOP=1 / all-intra.
- Payload: real Groth16 proof-bearing payload.
- Embedding mode: patchability-aware residual-coefficient modification.
- Verification:
  - strict non-blind via `verify()`,
  - sidecar-assisted near-blind via `verify_near_blind()`.

## Unsupported Or Future Work

- Full sidecar-free blind verification.
- CABAC / H.264 Main or High profile.
- HEVC/H.265.
- Robust survival under arbitrary recompression/transcoding.
- General inter-coded GOP support as a main claim.
- Trust-tier architecture such as C2PA, fingerprint registry proofs, TEE, or
  ZKML.

## Payload Budget

Current legacy payload format:

```text
[4B message_length][message][129B compressed Groth16 proof]
```

Benchmark payload:

- message: `13` bytes, usually `b"ZK-bench-v1.0!"`
- proof: `129` bytes
- header: `4` bytes
- packed payload: `146` bytes = `1168` bits
- chaos-expanded benchmark operating payload: `1232` bits

## Capacity Vocabulary

Use these terms consistently:

- `raw_safe_bits`: CAVLC-safe candidate positions before stronger validation.
- `patchable_usable_bits`: positions surviving public API patchability checks.
- `validated_pool_bits`: benchmark-validated candidate pool.
- `operating_bits`: final locked operating-point positions.
- `applied_position_bits`: positions actually applied after reconstruction.

Do not report raw safe positions as final usable capacity.

## Quality Guard

Paper-grade operating-point results should satisfy:

- full real-proof embedding succeeds,
- proof verification succeeds,
- minimum modified-frame PSNR is above the selected guard, normally `40 dB`,
- average SSIM remains close to cover quality.

## Verification Assumptions

### Strict non-blind

`verify()` is the strongest verification path for development and benchmark
reproduction. It can use the original cover video or trusted precomputed
operating positions.

### Sidecar-assisted near-blind

`verify_near_blind()` does not require the original cover video, but it requires
sidecars:

- `.manifest.json`
- `.positions.json`

This is not full blind steganographic extraction.

### Blind-core

Blind-core diagnostics are future work. They must not be used as mainline
claims until real-proof full payload recovery and proof verification are stable
without sidecars.

## Test Evidence Semantics

The phase runner distinguishes:

- pass: the case executed and all assertions passed,
- fail: at least one assertion or unexpected exception occurred,
- skip: required assets, capacity, or native tools were unavailable.

Any phase with skipped core E2E cases is incomplete evidence, even when there
are no assertion failures.

## Performance Envelope

Current evidence separates:

- cold-start analysis/preprocessing,
- operational per-embed cost,
- proof generation,
- proof verification,
- extraction.

Cold-start video analysis can be expensive and should be treated as cacheable.
Paper tables should not collapse one-time preprocessing and warm operational
cost into one ambiguous number.
