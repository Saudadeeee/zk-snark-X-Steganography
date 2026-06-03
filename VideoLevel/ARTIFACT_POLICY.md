# Artifact Cleanup Policy

This policy defines which artifacts are kept, which are considered rebuildable,
and how benchmark outputs are tiered.

## Keep

### Paper-grade benchmark artifacts
- `benchmark/results/sec1_*.png`
- `benchmark/results/sec1_*.json`
- `benchmark/results/sec2_*.png`
- `benchmark/results/sec2_*.json`
- `benchmark/results/sec3_methods*.png`
- `benchmark/results/sec3_methods*.json`
- `benchmark/results/sec4_*.png`
- `benchmark/results/sec4_*.json`
- `benchmark/results/sec6_*.png`
- `benchmark/results/sec6_*.json`
- `benchmark/results/sec*_statistical.json`
- `benchmark/results/sec6_paper_summary.txt`
- `benchmark/results/sec10_gop_sweep_data.json`

### Diagnostic-grade benchmark artifacts
- `benchmark/results/sec3_ablation.*`
- `benchmark/results/patchable_capacity_scan.json`
- `benchmark/results/_run_metadata.json`

### Documentation
- `README.md`
- `plan.md`
- `PAPER_EVIDENCE.md`
- `OPERATING_ENVELOPE.md`
- `COMPARATIVE_ANALYSIS.md`
- `COMPLETION.md`

## Rebuildable / Auto-clean Candidates

### Stego outputs
- `data/output/*.h264`
- `data/output/*.positions.json`
- `data/output/*.validated_pool.json`
- `data/output/*.meta.json`
- `data/output/*.manifest.json`

### Caches
- `.cache/video_analysis/*.pkl`
- `.cache/benchmark_frames/*.npy`
- `benchmark/results/_proof_payload_cache.bin`
- `benchmark/results/_idr_cache_*.pkl`
- `.pytest_cache/`
- `__pycache__/`

### Temporary / diagnostic intermediates
- `data/output/_sec*.h264`
- `benchmark/results/_run_metadata.json`

## Never Commit

- `data/raw/*.y4m`
- `data/encoded/*.h264`
- `circuits/build/*.zkey`
- `circuits/build/*.wasm`
- `circuits/node_modules/`
- `.cache/`

## Cleanup Commands

### Controlled cleanup helper
```bash
py -3.12 benchmark/clean_artifacts.py --diagnostic
py -3.12 benchmark/clean_artifacts.py --stego
py -3.12 benchmark/clean_artifacts.py --cache
py -3.12 benchmark/clean_artifacts.py --all-rebuildable
```

### Manual cleanup
```bash
rm -f data/output/*.h264 data/output/*.json
rm -rf .cache/
rm -rf __pycache__/ src/__pycache__/ benchmark/__pycache__/
```

## Notes

- `safe_benchmark_runner.py` now distinguishes `paper_grade` vs `diagnostic_grade`
  sections, so diagnostic outputs should not block paper-grade automation.
- The strongest reproducible E2E path currently uses locked operating-point
  artifacts, so deleting `positions.json` / `manifest.json` will remove that
  reproduction path until they are regenerated.
