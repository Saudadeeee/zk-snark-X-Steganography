# Benchmark Suite — ZK-SNARK DICOM Steganography

This folder contains the complete benchmark implementation for the paper
*"ZK-SNARK DICOM Steganography with Chaos-Based Position Selection"*.

---

## Folder Structure

```
Benchmark/
├── run_all.py                    ← Master runner (all sections)
├── common.py                     ← Shared utilities, baseline embedders, RS/chi²/SPA
│
├── Quality/                      ← §1 Image quality metrics
│   ├── quality_metrics.py        — PSNR, SSIM, MSE, BPP per DICOM image (bar + line charts)
│   ├── histogram_overlay.py      — Cover vs stego pixel histogram (F1)
│   ├── lsb_planes.py             — Bit-plane 0/1 visualisation (F2)
│   └── results/                  ← auto-generated PNG, JSON
│
├── Steganalysis/                 ← §2 Steganalysis resistance
│   ├── rs_analysis.py            — RS Analysis: Rm-Sm grouped bar chart
│   ├── chi_square.py             — Chi-square p-value bar chart (note: inapplicable to 16-bit)
│   ├── spa_analysis.py           — SPA payload estimate bar chart
│   └── results/
│
├── Baseline/                     ← §3 Payload sweep (detection vs embedding rate)
│   ├── psnr_vs_payload.py        — PSNR vs BPP — line chart per method (F3)
│   ├── rs_vs_payload.py          — RS Rm-Sm + SPA p_hat vs BPP — dual line chart (F4)
│   └── results/
│
├── ZK/                           ← §4 ZK-specific metrics
│   ├── setup_circuit.py          — Compile circom + run Groth16 trusted setup
│   ├── correctness_tests.py      — 5 pass/fail correctness tests
│   ├── zk_timing.py              — Witness/prove/verify timing (line + bar charts)
│   ├── constraint_pie.py         — Constraint breakdown pie + bar chart
│   ├── zkp_scheme_comparison.py  — Proof size + scaling: Groth16 vs PLONK vs Bulletproofs vs STARK
│   └── results/
│
├── Performance/                  ← §5 Performance benchmarks
│   ├── timing_breakdown.py       — Per-phase timing stacked bar (F5)
│   ├── memory_profile.py         — tracemalloc peak RAM per phase
│   ├── file_size_overhead.py     — .dcm vs .png size delta
│   └── results/
│
├── SystemComparison/             ← §6 System-level comparison
│   ├── ecdsa_benchmark.py        — ECDSA P-256/384/521 sign/verify timing, size comparison
│   ├── stego_only_vs_zk.py       — Stego-only vs Stego+ZK vs Stego+ECDSA across payload sizes
│   ├── capability_radar.py       — Radar chart: 3 systems × 8 properties (F6)
│   └── results/
│
└── Security/                     ← §7 Security analysis
    ├── key_sensitivity.py        — Avalanche effect: position overlap vs key bit flips
    ├── two_key_separation.py     — Wrong-key extraction failure + position Jaccard overlap
    └── results/
```

---

## Quick Start

### 1. Install Python dependencies

```bash
cd ImageLevel
pip install numpy Pillow matplotlib scipy scikit-image pydicom cryptography
```

### 2. Add DICOM test files

Place at least 1 DICOM file in `examples/dicom/`:

```
ImageLevel/
└── examples/
    └── dicom/
        ├── 1-01.dcm
        ├── 1-02.dcm
        └── ...   (ideally 10 MR brain scans from TCIA)
```

### 3. Run all non-ZK benchmarks

```bash
cd ImageLevel
python Benchmark/run_all.py
```

### 4. Run ZK benchmarks (requires Node.js + circom)

```bash
# Step 1: Compile the circuit and run Groth16 trusted setup (one-time, ~10–30 min)
python Benchmark/ZK/setup_circuit.py

# Step 2: Run full benchmark suite including ZK timing
python Benchmark/run_all.py --with-zk
```

---

## Individual Sections

```bash
python Benchmark/run_all.py --section quality
python Benchmark/run_all.py --section steganalysis
python Benchmark/run_all.py --section baseline
python Benchmark/run_all.py --section zk
python Benchmark/run_all.py --section performance
python Benchmark/run_all.py --section syscompare
python Benchmark/run_all.py --section security
```

Or run a single file directly:

```bash
python Benchmark/Quality/quality_metrics.py
python Benchmark/Baseline/psnr_vs_payload.py
python Benchmark/ZK/zkp_scheme_comparison.py
python Benchmark/SystemComparison/capability_radar.py
python Benchmark/Security/key_sensitivity.py
```

---

## Paper Figure & Table Mapping

| Figure | File | Description |
|--------|------|-------------|
| **F1** | `Quality/histogram_overlay.py` | Cover vs stego pixel histogram |
| **F2** | `Quality/lsb_planes.py` | LSB bit-plane 0/1 visualisation |
| **F3** | `Baseline/psnr_vs_payload.py` | **PSNR vs payload rate (line chart)** |
| **F4** | `Baseline/rs_vs_payload.py` | **RS Rm-Sm + SPA vs payload rate (line charts)** |
| **F5** | `Performance/timing_breakdown.py` | Phase timing stacked bar |
| **F6** | `SystemComparison/capability_radar.py` | Capability radar chart |
| **F7** | `ZK/zkp_scheme_comparison.py` | ZK scheme scaling curves (line charts, log-log) |
| **F8** | `Security/key_sensitivity.py` | Avalanche effect (position overlap vs bit flips) |

| Table | File | Description |
|-------|------|-------------|
| **T1** | `Quality/quality_metrics.py` | PSNR, SSIM, MSE, BPP across 10 DICOM images |
| **T2** | `Steganalysis/rs_analysis.py` + others | RS Rm-Sm, chi², SPA results |
| **T3** | `ZK/correctness_tests.py` | 5-test correctness matrix |
| **T4** | `Performance/timing_breakdown.py` | Per-phase timing breakdown |
| **T5** | `ZK/zkp_scheme_comparison.py` | Groth16 vs PLONK vs Bulletproofs vs STARK |
| **T6** | `SystemComparison/capability_radar.py` | System capability scores (8 dimensions) |
| **T7** | `SystemComparison/ecdsa_benchmark.py` | ECDSA vs ZK timing comparison |

---

## Confirmed Benchmark Results

The following numbers were measured on 10 MR DICOM images (512×512, 16-bit uint16)
from the TCIA public dataset.

### §1 — Image Quality

| Metric | This Work | Sequential LSB | PRNG-LSB | ACM-only |
|--------|-----------|---------------|----------|----------|
| **PSNR (dB)** | **106.34** | 86.4 | 86.4 | 86.4 |
| **SSIM** | **1.0000** | 0.9999 | 0.9999 | 0.9999 |
| BPP | 0.0776 | 1.0 | 1.0 | 1.0 |

"This Work" uses only 2 LSBs across ~7.76% of pixels (sparse chaos embedding),
resulting in ~20 dB better PSNR than full-frame LSB methods.

### §2 — Steganalysis Resistance

| Method | RS Rm-Sm | SPA p_hat | Chi-square |
|--------|----------|-----------|------------|
| Cover | 0.507 | 0.000584 | n/a (16-bit) |
| **This Work** | **0.492** | **0.000400** | n/a (16-bit) |
| Sequential LSB | 0.468 | 0.000569 | n/a (16-bit) |
| PRNG-LSB | ~0.49 | ~0.0005 | n/a (16-bit) |

> **Note:** Chi-square attack is inapplicable to 16-bit DICOM images — the pair histogram
> is inherently degenerate (p=0 for all methods including unmodified cover images).
> This is an expected and correctly-reported finding.

"This Work" has the lowest RS delta and lowest SPA p_hat — it is the hardest to detect.

### §3 — Baseline Payload Sweep

- "This Work" maintains **+0.5 to +1.5 dB** higher PSNR than other methods at all payload rates
- RS detectability is **consistently lower** across the full BPP range 0.01–2.0

### §4 — ZK Scheme Comparison

| Scheme | Proof Size | Verify Time | Scalability | Trusted Setup |
|--------|-----------|-------------|-------------|---------------|
| **Groth16 (this work)** | **192 B** (constant) | ~1–3 ms | O(n log n) prove | Circuit-specific |
| PLONK | ~576 B (log n) | ~5–10 ms | O(n log n) prove | Universal SRS |
| Bulletproofs | O(log n) × 32 B | O(n) verify | Very slow prove | None |
| zk-STARK | O(n) bytes | Fast | O(n log² n) | None |

Circuit: 18,680 constraints, 28.5% pot16 utilization (BN254 curve).

**Groth16 is the best choice** for DICOM embedding: constant 192-byte proof fits
in any DICOM file, and ~1 ms verification. Non-Groth16 rows are literature models
(dashed lines in charts) — hardware and security level may differ.

New outputs from `zkp_scheme_comparison.py`:
- `zkp_proof_size_line.png` — 2×2 log-log scaling curves (proof size, prover time, verify time vs constraints)
- `zkp_embeddability_line.png` — linear zoom showing which schemes fit within DICOM capacity (~10 KB)
- `zkp_scheme_comparison.png` — bar chart comparison at this circuit's constraint count

### §5 — Performance

| Phase | Time | Peak RAM |
|-------|------|----------|
| Chaos position selection | 1.23 s | — |
| LSB embedding | 2.64 s | — |
| **Total** | **3.93 s** | **68.8 MB** |
| File size: DICOM → PNG | 522 KB → 112 KB | **−78.5%** |

### §6 — System Comparison

| Operation | This Work | Stego Only | Stego + ECDSA P-256 |
|-----------|-----------|------------|---------------------|
| Embed time | ~2.76 s | ~2.76 s | ~2.76 s + 0.14 ms |
| Extract time | ~4.93 s | ~4.93 s | ~4.93 s + 0.06 ms |
| Auth overhead | 192 B (ZK proof) | 0 B | ~70 B (ECDSA sig) |
| Integrity verification | ZK (zero-knowledge) | None | Hash + PKI |
| Post-quantum resistant | No (BN254) | Yes | No (ECDLP) |
| Requires PKI | No | No | Yes |

ECDSA timing: sign = 0.14 ms, verify = 0.06 ms (P-256, 20-run mean, OpenSSL warmed up).

### §7 — Security

| Test | Result |
|------|--------|
| 1-bit key flip → position overlap | **< 5%** (avalanche effect confirmed) |
| 64-bit key flip → position overlap | **~0%** |
| Wrong-key extraction | **FAIL** (SHA-256 hash mismatch) |
| Two-key position Jaccard overlap | **< 0.01%** |

The chaos map exhibits a strong avalanche effect: even a single bit change in the
128-bit key shuffles >95% of embedding positions.

---

## Color Conventions

All charts use a shared color palette from `common.py`:

| Method | Color | Hex |
|--------|-------|-----|
| Cover (baseline) | Blue | `#2196F3` |
| Sequential LSB | Red | `#F44336` |
| PRNG-LSB | Green | `#4CAF50` |
| ACM-only | Orange | `#FF9800` |
| **This Work** | **Purple** | **`#9C27B0`** |

Line charts use solid lines for measured data and dashed lines for literature models.

---

## Notes

- All charts saved as `.png` in the respective `results/` subfolder
- JSON files with raw numbers saved alongside each chart
- `--with-zk` flag required for ZK timing (`correctness_tests.py`, `zk_timing.py`)
- ECDSA benchmark requires `pip install cryptography`
- SSIM computation requires `pip install scikit-image`
- Chi-square attack is expected to give p=0 for all 16-bit DICOM images — this is a
  documented limitation of the attack, not a bug in the implementation
