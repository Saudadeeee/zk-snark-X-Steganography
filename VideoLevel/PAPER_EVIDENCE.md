# Paper Evidence Notes

Last updated: 2026-06-08

This file records the current evidence that can support paper writing. It is not
a manuscript. It is a claim-to-evidence map for the frozen current system.

## Frozen Baseline

The current paper baseline is:

- locked operating-point embedding,
- all-intra H.264 baseline / CAVLC,
- real Groth16 proof payload,
- strict non-blind verification,
- sidecar-assisted near-blind verification,
- blind-core as future work only.

## Defensible Contributions

### 1. Compressed-domain proof-bearing video steganography

The system embeds a Groth16 proof-bearing payload into H.264/CAVLC residual
coefficient positions without using a pixel-domain rewrite workflow.

### 2. Patchability-aware operating point

The system distinguishes raw candidates from positions that can actually be
patched into a valid bitstream and survive reconstruction.

### 3. Reconstruction-aware capacity accounting

The implementation records not only intended capacity but also the number of
positions actually applied after reconstruction.

### 4. Sidecar-assisted near-blind verification

The verifier can avoid requiring the original cover video when authenticated
sidecar metadata and operating positions are available.

### 5. ZKP-authenticated hidden payload

Extracted payload bytes are verified as a Groth16 proof relation:

```text
commitment = SHA256(SHA256(message) || secret_key)
```

## Verifier Modes

| Mode | Required inputs | Cover required | Sidecar required | Status |
|---|---|---:|---:|---|
| `verify()` | stego video, original cover or trusted positions, secret key, circuits | Yes by default | Optional | Stable baseline |
| `verify_near_blind()` | stego video, manifest, positions, secret key, circuits | No | Yes | Stable baseline |
| blind-core | stego video only plus verification inputs | No | No | Future work |

Recommended wording:

- `verify()` = strict non-blind verification.
- `verify_near_blind()` = sidecar-assisted near-blind verification.
- blind-core = not a current system claim.

## Capacity Terms

| Term | Meaning |
|---|---|
| `raw_safe_bits` | CAVLC-safe positions before patchability and operating validation |
| `patchable_usable_bits` | positions surviving public API patchability flow |
| `validated_pool_bits` | benchmark-validated candidate pool |
| `operating_bits` | final locked operating-point positions |
| `applied_position_bits` | positions actually applied after reconstruction |

Do not collapse these terms into one capacity number.

## Current Evidence Snapshot

The current committed paper-grade JSON records the following snapshot:

- SEC1 locked operating point: `akiyo_q22_g1`.
- Operating payload: `1232/1232` bits.
- End-to-end verification: `verify_valid=true`, `verify_message_match=true`.
- Full-video PSNR: `53.01 dB`.
- Minimum modified-frame PSNR: `40.30 dB`.
- Average SSIM: `0.9997`.
- SEC2 capacity layers:
  - `raw_safe_bits`: `413415`,
  - `patchable_usable_bits`: `2000`,
  - `validated_pool_bits`: `1449`,
  - `operating_bits`: `1232`.
- SEC4 detector examples from the committed SEC4 artifact:
  - chi-square p-value `0.9622`,
  - SPA `0.03762`,
  - RS delta `0.0`.
- SEC5 proof-overhead snapshot from the committed SEC5 artifact:
  - Groth16 packed proof-bearing payload: `147 B`,
  - Groth16 prove time: `1556.58 ms`,
  - Groth16 verify time: `8.5 ms`.
- SEC6 split from the committed SEC6 artifact:
  - pre-processing is separated from operational cost,
  - current committed `akiyo_q22_g1` run reports `59.0s` pre-processing,
    `26.1s` operational cost, and `85.0s` total.
  - standalone ZK prove is reported as `0.0s` because proof generation is
    included inside the combined public embed stage.

These numbers must be refreshed from live benchmark JSON before final
submission if any code or artifact changes after this freeze.

## Current Validation Status

Latest local phase validation after explicit skip accounting:

- quick suite: `23/23` passed,
- Phase 4 reconstruction: `5/5` passed,
- Phase 5 public API E2E: `2/2` passed,
- Phase 6 near-blind E2E: `2/2` passed,
- Phase 7 regression fixtures: `3/3` passed,
- full suite: `35/35` passed, `0` failed, `0` skipped.

Phase 7 now uses the verified SEC1 artifact for `akiyo_q22_g1` and can be used
as regression evidence for the current frozen baseline.

SEC1 artifact policy now requires verified metadata before an artifact can be
used as a locked operating contract. Failed SEC1 attempts must not leave
contract-looking sidecars behind.

## Claims Supported Now

- The system is strongest under all-intra H.264/CAVLC.
- The locked operating point can carry a real proof payload.
- Sidecar-assisted near-blind verification exists and is distinct from full
  blind extraction.
- Capacity must be reported in layers.
- Patchability and reconstruction checks are core to the system, not cosmetic.

## Claims Not Supported Yet

- Full blind extraction.
- Robust watermarking under recompression.
- Broad support for arbitrary H.264 streams.
- CABAC/HEVC support.
- C2PA/fingerprint/TEE/ZKML trust architecture.

## Upgrade-v2 Trust Evidence Gate

The `Upgrade-v2` branch now keeps future trust-plane results in separate
sections:

- Section 44: diagnostic trust architecture replay.
- Section 45: claim-gated trust evidence distilled from Section 44.

Latest local Section 45 replay reports:

- claim gates: `6/6` passed,
- `promotion_ready=true`,
- corpus validation: local registered corpus `22/22` present, external seed
  corpus `1/1` present,
- no promotion blockers remain for the seed corpus contract.

This supports branch-level development claims for C2PA anchoring, local-corpus
fingerprint lookup, keyed-template watermark receipt, mock TEE attestation, and
toy ZK receipt circuits. The ready-to-use API surface is `src.trust.workflows`
and covers provenance, fingerprint registry, watermark receipt, and
attestation workflows. For broad public-dataset claims, the seed corpus is not
enough; keep that wording separate from the promoted seed-corpus evidence.

## Final Paper Checklist

- [x] Re-run paper-grade benchmarks after final code freeze.
- [x] Restore Phase 5/6 E2E coverage so they pass without skips.
- [x] Restore Phase 7 fixture coverage so it passes without skips.
- [x] Regenerate at least one verified SEC1 operating artifact with
      `verify_valid=true`.
- [x] Update SEC1/SEC2/SEC3/SEC4/SEC5/SEC6 tables from current JSON.
- [x] Record exact commands and environment.
- [ ] Keep blind-core in future work.
- [ ] Keep trust-tier architecture in future work or a separate branch.
