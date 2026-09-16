# Current-System Completion Summary

Last updated: 2026-09-16

This file summarizes the current-system completion target. It intentionally does
not include future architecture work such as robust watermarking, C2PA tiers,
fingerprint registries, TEE, or ZKML.

## Completed Baseline Capabilities

- H.264/CAVLC compressed-domain embedding path.
- Groth16 proof generation and verification bridge.
- 129-byte compressed proof serialization.
- Payload packing:
  `[4B message_length][message][129B proof]`.
- Patchability-aware candidate filtering.
- Reconstruction-aware applied-position accounting.
- Authenticated Manifest v2.0.0 sidecar (Ed25519, stego-hash and positions-hash binding).
- Strict non-blind verifier.
- Sidecar-assisted near-blind verifier.
- Benchmark sections for quality, capacity, method comparison, security, ZKP,
  performance, tradeoff, realtime/motion/GOP, and statistics.
- Detailed LaTeX walkthrough in `doc/`.

## Current Paper Baseline Status

The current baseline is frozen for paper drafting under the current operating
contract:

- all-intra H.264/CAVLC operating envelope,
- locked `akiyo_q22_g1` operating-point real-proof embedding,
- sidecar-assisted near-blind verification,
- blind-core labeled future work.

## Freeze Checklist

- [x] Run quick test suite.
- [x] Run Phase 4 reconstruction test.
- [x] Fix test skip semantics so skipped E2E cases are not counted as passed.
- [x] Prevent failed SEC1 runs from publishing contract-looking sidecars.
- [x] Require verified SEC1 metadata before loading a locked operating contract.
- [x] Restore Phase 5 public API E2E coverage without skips.
- [x] Restore Phase 6 near-blind E2E coverage without skips.
- [x] Restore Phase 7 regression fixture artifacts or rewrite fixtures so they
      exercise committed assets.
- [x] Re-run relevant benchmark sections after benchmark code changes.
- [x] Refresh `PAPER_EVIDENCE.md` wording from current JSON and current
      committed artifacts.
- [x] Confirm README links and documentation are consistent after benchmark
      reruns.

Current hardening validation (2026-09-16):

- quick runtime suite: `23/23` passed;
- security/reproducibility hardening: `6/6` passed;
- generated FFmpeg codec/decode fixture: `1/1` passed;
- circuit package contract and artifact checksum verification passed.

The previous full-suite and benchmark results above predate the enforced
payload-length constraint and authenticated manifest v2. They must be rerun
with freshly generated signed v2 sidecars before being used as current evidence.

## Not Part Of Current Completion

- Robust mode.
- Full blind verifier.
- C2PA bridge.
- Fingerprint registry circuit.
- ZK watermark receipt circuit.
- TEE attestation.
- ZKML.
