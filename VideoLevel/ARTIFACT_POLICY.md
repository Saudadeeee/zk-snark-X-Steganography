# Artifact Cleanup Policy

This policy defines which artifacts are kept, excluded, and auto-cleaned.

## Keep (tracked in git / results)

### Benchmark Results
- `benchmark/results/*.json` — Final benchmark data
- `benchmark/results/*.png` — Plots and figures
- `benchmark/results/sec*_statistical.json` — Multi-run statistics
- `benchmark/results/sec6_paper_summary.txt` — Paper-ready timing text
- `benchmark/results/sec10_gop_sweep_data.json` — GOP sweep results

### Test Artifacts
- No test intermediates (use ephemeral directories)

### Documentation
- `plan.md` — Project status tracking
- `README.md` — Project overview
- All `.md` files

## Auto-clean (deleted on each run)

### Stego Outputs
- `data/output/*.h264` — Temporary stego videos (rebuildable)
- `data/output/*.positions.json` — Positions files (rebuildable)
- `data/output/*.meta.json` — Legacy metadata (rebuildable)
- `data/output/*.manifest.json` — Versioned manifest (rebuildable)

### Analysis Cache
- `.cache/video_analysis/*.pkl` — Cover video analysis
- `.cache/benchmark_frames/*.npy` — Luma frame cache

### Proof Cache
- `benchmark/results/_proof_payload_cache.bin` — ZK proof cache

### Python Cache
- `__pycache__/` — All directories
- `*.pyc` — Bytecode
- `*.pyo` — Optimized bytecode

### Other
- `.DS_Store` — macOS metadata
- `Thumbs.db` — Windows thumbnails

## Exclude (never committed)

### Data Files
- `data/raw/*.y4m` — Large raw videos (downloadable)
- `data/encoded/*.h264` — Large encoded videos (regenerate from raw)

### Circuit Build Artifacts
- `circuits/build/*.zkey` — Large proving keys (>100MB each)
- `circuits/build/*.wasm` — WASM outputs
- `circuits/node_modules/` — Node.js dependencies

### Cache Directories
- `.cache/` — All cache subdirectories
- `.pytest_cache/` — Pytest cache

## Cleanup Commands

### Clean rebuildables (safe to run)
```bash
# Remove all stego outputs
rm -f data/output/*.h264 data/output/*.json

# Clear caches
rm -rf .cache/
rm -rf __pycache__/ src/__pycache__/ benchmark/__pycache__/
```

### Clean all (restore to git state)
```bash
# Remove everything not tracked
git clean -fdx

# Rebuild from scratch
py -3.12 -m pip install -r requirements.txt
cd circuits && npm install
```

## Cache Management

### Cache Key Structure
- Video analysis cache: Keyed by `(file_path, file_size, file_mtime, config_fingerprint)`
- Luma decode cache: Keyed by `(file_path, size, mtime)`
- Proof cache: Keyed by `SHA1(message || secret_key)`

### Cache Invalidation
- Video analysis: Invalidates on config change or file modification
- Luma frames: Invalidates on file size/mtime change
- Proof cache: Invalidates on message or secret_key change

### Cache Limits
- Video analysis: Unlimited (depends on number of distinct videos)
- Luma frames: ~500MB per benchmark session (configurable)
- Proof cache: 1MB (single blob)

## Disk Usage Estimates

| Category | Typical Size | Notes |
|----------|-------------|-------|
| Raw video (CIF, 300f) | 44MB | Per sequence |
| Encoded video (QP22, g1) | 2.9MB | Per sequence |
| Stego output | 2.9MB | Per embedding |
| Analysis cache | ~10MB | Per video |
| Luma cache | ~50MB | Per benchmark session |
| Benchmark results | ~5MB | All sections |
| Circuit zkeys | ~200MB | Groth16 proving key |

## Best Practices

1. **Before commit:** Run `git clean -fdx` to remove rebuildables
2. **Before benchmark:** Clear caches with `rm -rf .cache/`
3. **After benchmark:** Results auto-saved to `benchmark/results/`
4. **CI/CD:** Use cache mounts for `.cache/` to speed up builds
5. **Paper figures:** Manually verify `benchmark/results/*.png` before submission