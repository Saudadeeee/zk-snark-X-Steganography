# Artifact Policy

Last updated: 2026-06-08

This policy defines which files are part of the current reproducible baseline
and which files are rebuildable diagnostics or local cache.

## Keep In Repository

### Source and tests

- `src/**`
- `benchmark/*.py`
- `src/trust/**`
- `src/trust/workflows.py`
- `src/provenance/**`
- `src/runtest/test_future_trust_architecture.py`
- `benchmark/trust_architecture_diagnostic.py`
- `benchmark/sec45_trust_evidence.py`
- `benchmark/trust_corpus.py`
- `benchmark/trust_corpus_manifest.json`
- `circuits/payload_verify.circom`
- `circuits/package.json`
- `requirements.txt`
- `requirements.lock`

### Main documentation

- `README.md`
- `plan.md`
- `system.txt`
- `PAPER_EVIDENCE.md`
- `OPERATING_ENVELOPE.md`
- `ARTIFACT_POLICY.md`
- `COMPARATIVE_ANALYSIS.md`
- `COMPLETION.md`
- `doc/trust_corpus_onboarding.md`
- `doc/system_video_embedding_walkthrough.tex`
- `doc/system_video_embedding_walkthrough.pdf`

### Paper-grade benchmark outputs

Keep benchmark outputs that are directly referenced by paper evidence:

- `benchmark/results/sec1_*.json`
- `benchmark/results/sec1_*.png`
- `benchmark/results/sec2_*.json`
- `benchmark/results/sec2_*.png`
- `benchmark/results/sec3_methods*.json`
- `benchmark/results/sec3_*.png`
- `benchmark/results/sec4_*.json`
- `benchmark/results/sec4_*.png`
- `benchmark/results/sec5_*.json`
- `benchmark/results/sec5_*.png`
- `benchmark/results/sec6_*.json`
- `benchmark/results/sec6_*.png`
- `benchmark/results/sec7_*.json`
- `benchmark/results/sec7_*.png`
- `benchmark/results/trust_architecture_diagnostic.json`
- `benchmark/results/trust_corpus_validation.json`
- `benchmark/results/sec45_trust_evidence_data.json`
- `benchmark/results/sec45_trust_evidence_summary.png`

## Rebuildable Or Local Only

These files can be regenerated and should normally stay out of commits unless a
specific paper table depends on them:

- `.cache/**`
- `.pytest_cache/**`
- `__pycache__/**`
- `benchmark/results/_idr_cache_*.pkl`
- `benchmark/results/_proof_payload_cache.bin`
- `benchmark/results/_run_metadata.json`
- `benchmark/results/sec6_paper_summary.txt`
- `data/output/*.h264`
- `data/output/*.positions.json`
- `data/output/*.meta.json`
- `data/output/*.manifest.json`

## Never Commit

- `data/raw/*.y4m`
- `data/raw/*.h264`
- `data/encoded/*.h264`
- `circuits/node_modules/**`
- `circuits/build/*.zkey`
- `circuits/build/*.wasm`
- local scratch scripts such as `debug_*.py`, `tmp*.py`, `check_*.py`

## Cleanup Commands

Use the controlled helper first:

```bash
py -3.12 benchmark/clean_artifacts.py --diagnostic
py -3.12 benchmark/clean_artifacts.py --stego
py -3.12 benchmark/clean_artifacts.py --cache
```

Manual cleanup is acceptable for local-only artifacts:

```bash
Remove-Item -Recurse -Force .pytest_cache
Remove-Item -Recurse -Force .cache
```

## Policy Notes

- Do not mix blind-core diagnostics into paper-grade evidence.
- Do not mix future trust architecture diagnostics into the frozen baseline
  paper-grade evidence. On `Upgrade-v2`, use section `45` as a claim-gated
  evidence layer and keep promotion blockers explicit.
- Do not use raw safe-position counts as final capacity evidence.
- Keep sidecar files only when they are needed to reproduce a specific
  operating-point artifact.
- Future architecture artifacts for C2PA, robust watermarking, TEE, or ZKML
  should be added on a separate branch, not mixed into the current-system
  baseline.

## Required Native Tooling

The audited current baseline expects the following local tools to be present:

- Python 3.12.10 observed locally
- Node.js 22.20.0 observed locally
- `circom` 2.2.x
- `snarkjs` 0.7.6 observed locally
- `ffmpeg` 8.0.1 observed locally

These tools are used for circuit compilation, witness/proof generation, video
encoding/validation, and benchmark replay.
