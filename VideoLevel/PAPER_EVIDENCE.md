# Paper Evidence Notes

Last updated: 2026-05-29

This document summarizes the current paper-facing evidence in a compact form.
It is not a manuscript, but a staging note for tables, claims, and framing.

Frozen baseline for paper writing:
- core system claim = locked operating-point embedding on all-intra H.264/CAVLC
- strongest verifier claim = strict non-blind verification
- practical deployment claim = sidecar-assisted near-blind verification
- blind-core branch = research / future work only
- blind-core must not be positioned as a mature verifier path in the current paper

---

## Contribution Framing

The current repository can support the following contribution framing more
defensibly than broader claims:

1. **Compressed-domain ZK steganography for all-intra H.264/CAVLC**
- The system hides a Groth16-backed payload in CAVLC residual coefficients
- The strongest regime is all-intra H.264 baseline with CAVLC

2. **A locked operating-point pipeline with full public-API E2E validation**
- The repository now contains a public-API operating contract that passes
  end-to-end embedding, extraction, and proof verification in-tree

3. **A multi-level capacity model for honest reporting**
- The implementation and benchmark stack distinguish:
  - raw safe bits
  - patchable usable bits
  - validated pool bits
  - operating bits

4. **Evidence that operating-point success depends on specific engineering choices**
- Internal ablations show that:
  - removing quality guard breaks payload realization
  - removing round-robin distribution breaks payload realization
  - removing patchability-aware pruning breaks payload realization

5. **A sidecar-assisted near-blind verification path**
- Verification can be performed without the original cover video
- This mode still requires authenticated sidecar metadata

---

## Verifier Modes

| Mode | Inputs required at verification time | Cover video required | Sidecar required | Current status |
|---|---|---:|---:|---|
| `verify()` | `stego video`, `original video` or trusted precomputed operating positions, `secret_key`, `circuits` | Yes, by default | No | Stable |
| `verify_near_blind()` | `stego video`, `manifest.json`, `positions.json`, `secret_key`, `circuits` | No | Yes | Stable |
| Blind mode | `stego video`, `secret_key`, `circuits` | No | No | Not implemented |

Recommended wording:
- `verify()` = strict non-blind verification
- `verify_near_blind()` = sidecar-assisted near-blind verification

---

## Capacity Vocabulary

Use the following terms consistently:

| Term | Meaning |
|---|---|
| `raw_safe_bits` | CAVLC-safe candidate positions before patchability and quality validation |
| `patchable_usable_bits` | positions surviving the public API patchability flow |
| `validated_pool_bits` | SEC1 validated candidate pool after hard-error / quality validation |
| `operating_bits` | exact positions used at the locked SEC1 operating point |

Do not collapse these terms into a single "capacity" number in the paper.

---

## Locked Operating Point Evidence

Current benchmark-grade operating contract:
- stream class: all-intra H.264 baseline / CAVLC
- payload mode: real-proof payload
- strongest benchmark path: locked operating positions from SEC1

Evidence currently available:
- Phase 5 public API E2E passes in-tree using locked operating-point mode
- Phase 6 sidecar-assisted near-blind E2E passes in-tree on the same contract
- quick suite remains clean (`23/23`)
- broad public-API diagnostic currently under-fills before reconstruction on representative all-intra assets when locked operating positions are not supplied

---

## Capacity Evidence Snapshot

Representative SEC2 fast-sweep outputs currently show:

| Sequence | Raw safe bits | Patchable usable bits | Validated pool bits | Operating bits |
|---|---:|---:|---:|---:|
| `coastguard_q22_g1` | 433,256 | 1,391 | 1,316 | 1,232 |
| `deadline_q22_g1` | 1,775,749 | 1,383 | 1,321 | 1,232 |

Interpretation:
- raw-safe counts are very loose upper bounds
- patchable usable bits are much closer to what the public API can realize
- operating bits are the true benchmark-grade payload budget

---

## Internal Ablation Snapshot

Source: `benchmark/results/sec3_ablation_data.json`

Sequence currently selected:
- `deadline_q22_g1`

| Variant | Success | Bits embedded | Full-video PSNR |
|---|---:|---:|---:|
| `locked_operating_point` | Yes | 1232 | 56.94 dB |
| `no_quality_guard` | No | 0 | N/A |
| `no_round_robin` | No | 0 | N/A |
| `no_patchability_pruning` | No | 0 | N/A |
| `locked_no_chaos` | Yes | 1176 | 55.83 dB |

Takeaways:
- locked operating-point positions are essential for realizing the 1232-bit operating point
- removing the quality-guarded operating-point contract breaks payload realization
- removing round-robin ordering also breaks payload realization
- removing patchability-aware pruning also breaks payload realization
- disabling chaos reduces payload from 1232 bits to 1176 bits with only a small PSNR shift
- these ablations suggest the current system gain is driven more by the locked
  operating contract than by a loose raw-safe candidate count
- diagnostics now show that the failing ablations typically collapse at the
  `post_reconstruct_application` stage rather than at initial candidate sizing

---

## Claims That Are Defensible Now

- The system is strongest in all-intra H.264/CAVLC streams.
- A locked operating point with full public-API E2E verification exists in-tree.
- Near-blind verification is currently sidecar-assisted, not blind.
- Capacity must be reported using multiple levels rather than one nominal number.
- The operating-point contract, not just the safety filter, is a material contributor to success.
- The current ablation evidence already supports a reviewer-facing argument that
  quality guard, round-robin distribution, and patchability-aware pruning are
  not cosmetic heuristics.

---

## Claim To Evidence Table

| Claim | Current support | Evidence source |
|---|---|---|
| The system is strongest in all-intra H.264/CAVLC streams | Strong | SEC1 operating-point results, README scope, verifier/e2e fixtures |
| A locked operating point passes full public-API E2E in-tree | Strong | Phase 5 public API E2E, Phase 6 near-blind E2E |
| Near-blind verification is sidecar-assisted rather than blind | Strong | `verify_near_blind()` contract and verifier-mode documentation |
| Capacity must be reported as multiple levels, not one nominal number | Strong | SEC2 four-level reporting, capacity vocabulary |
| The operating-point contract is a material contributor to success | Strong | `locked_operating_point` vs `no_quality_guard` ablation |
| Round-robin distribution materially contributes to payload realization | Strong | `locked_operating_point` vs `no_round_robin` ablation |
| Patchability-aware pruning materially contributes to payload realization | Strong | `locked_operating_point` vs `no_patchability_pruning` ablation |
| Chaos mainly changes the payload contract rather than collapsing quality | Moderate | `locked_operating_point` vs `locked_no_chaos` ablation |
| The current system is blind | Unsupported | No sidecar-free extraction path implemented |
| The current system broadly supports inter-coded H.264 | Unsupported | Operating regime still collapses outside the strongest all-intra path |

---

## Candidate Paper Tables

Recommended manuscript tables:

1. **Verifier mode table**
- inputs required
- cover video required or not
- sidecar required or not
- current implementation status

2. **Capacity table**
- raw safe bits
- patchable usable bits
- validated pool bits
- operating bits

3. **Operating-point table**
- asset
- payload bits required
- payload bits embedded
- verification status
- PSNR / SSIM

4. **Ablation table**
- locked operating point
- no quality guard
- no round-robin
- no patchability-aware pruning
- locked no chaos

---

## Claims That Still Need More Work

- General H.264 support beyond all-intra
- Fully blind verification
- Broad public-API payload realization without locked operating positions
- Broader ablations beyond the current operating-contract family
- Final paper-grade baseline table across all comparison families

Paper-writing guidance:
- Use the frozen baseline above as the main narrative.
- Treat blind-core results as evidence of a promising research direction, not as
  a mature system capability.

Broad public-API realization snapshot:
- `benchmark/results/public_api_realization.json`
- representative all-intra assets currently fail in generic mode at
  `pre_reconstruct_embedding`, with realized budgets around:
  - `coastguard_q22_g1`: 832 bits
  - `deadline_q22_g1`: 812 bits
  - `coastguard_q22_g1_1000f`: 842 bits
  - `foreman_q22_g1`: 763 bits

Blind-sync diagnostic status:
- `benchmark/results/blind_sync_diagnostic.json` currently shows:
  - zero overlap for the strict stable-candidate prototype
  - non-zero but still tiny overlap (`2/1232`) for both:
    - chaos+dedup ordering
    - operating-like chaos+dedup+per-IDR-cap ordering
  - the strongest current bridge actually comes from the validated-pool proxy search:
    - `benchmark/results/validated_pool_proxy_diagnostic.json`
    - best validated-pool overlap = `78/1321`
    - best operating-position overlap = `75/1232`
    - best current contract uses:
      - benchmark sync key
      - full safe-position universe
      - per-block deduplication
      - no bottom-zone restriction
      - no per-IDR cap
  - this suggests the validated pool is currently closer to a broad deduplicated
    safe-position universe than to the stricter sign-bit / bottom-zone heuristics

Blind-core self-consistency status:
- `benchmark/results/blind_core_trial.json`
- using the validated-pool-proxy derivation on the selected SEC1 artifact:
  - cover/stego set overlap = `1176/1176`
  - cover/stego prefix match = `1176/1176`
- this is the first strong sign that a sidecar-free blind candidate universe may
  be achievable if the payload contract is aligned with the blind derivation

Blind header diagnostic status:
- `benchmark/results/blind_header_redundancy_diagnostic.json`
- on the selected blind-core asset:
  - redundancy `1`: header decode succeeds
  - redundancy `4`: header decode succeeds
  - redundancy `8`: header decode succeeds
  - redundancy `2`: header decode fails
- this means header readout is no longer uniformly broken; it is sensitive to
  how the header contract is coded

Blind-core freeze note:
- blind-core is now explicitly treated as a future-work branch
- the current blocking issue is header readout reliability
- no blind end-to-end operating contract should be claimed as usable in the
  current manuscript
- This means blind synchronization architecture is still at the prototype /
  diagnostic stage and must not be claimed as working verification logic yet
