# Comparative Analysis Notes

Last updated: 2026-06-06

This file provides cautious comparison framing for the current system. It should
not be treated as final related-work text without citation cleanup.

## Current System

The current system is best described as:

- H.264 baseline / CAVLC compressed-domain embedding,
- patchability-aware residual-coefficient modification,
- real Groth16 proof payload,
- locked operating-point benchmark evidence,
- sidecar-assisted near-blind verification.

## Comparison Axes

Use these axes when comparing with prior video steganography work:

- embedding domain: pixel, transform, H.264 syntax, CAVLC/CABAC, motion vector,
- payload authenticity: none, MAC/signature, ZKP proof,
- capacity accounting: raw capacity vs realized/reconstructable capacity,
- video quality: full-video PSNR, modified-frame PSNR, SSIM,
- detector behavior: chi-square, SPA/RS, WS, SPAM, modern feature detectors,
- verifier dependency: cover-required, sidecar-assisted, fully blind,
- codec envelope: all-intra CAVLC vs inter-coded/CABAC/HEVC.

## Safe Comparative Claims

- The system adds a proof-verification layer that conventional video
  steganography systems typically do not provide.
- The system reports capacity more conservatively by separating raw safe
  positions from patchable and operating positions.
- The system is intentionally lower-capacity than aggressive embedding methods
  because it enforces patchability and quality constraints.
- The current near-blind verifier reduces cover dependency but still requires
  sidecar metadata.

## Claims To Avoid

- Do not claim universal superiority over all prior video steganography.
- Do not claim robust recompression survival.
- Do not claim full blind extraction.
- Do not compare detector p-values without matching payload, codec, QP, GOP,
  and sequence conditions.
- Do not describe future C2PA/fingerprint/TEE/ZKML work as implemented.

## Paper Positioning

The best paper framing is not "highest-capacity video steganography".

The stronger framing is:

> proof-verifiable compressed-domain video steganography with
> patchability-aware operating-point discipline.

This makes the lower operating capacity a deliberate tradeoff for
reconstructability, quality, and verifiable payload semantics.
