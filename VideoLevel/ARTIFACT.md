# Artifact: lattice-ZK proofs carried inside H.264 video

This file tells a reviewer how to rerun the evaluation of the lattice
zero-knowledge video system (`src/lattice_zk/`, parameter set
`bdlop-open-128-v2`): from the unit tests (about a minute) through one short
end-to-end run (10-15 minutes) to the full multi-clip sweep (tens of hours).
Every command is run from `VideoLevel/`. Each step has a PowerShell (`.ps1`)
and a POSIX (`.sh`) wrapper in `scripts/`. Both call `scripts/repro.py`, which
needs only the standard library.

Status: research prototype. The protocol was implemented by the authors from
published papers and has not been audited (see `docs/LATTICE_ZK_BDLOP_SPEC.md`).

## 1. Contents

| Path | What it is |
|---|---|
| `src/lattice_zk/` | BDLOP commitment, opening / equality / linkage proofs, video statement and envelope, embed/verify pipeline, role-separated CLI |
| `src/blind_sync*.py`, `src/blind_payload_chunks.py`, `src/core/analysis_cache.py`, `src/bitstream/` | Carrier analysis, chunk framing and CAVLC patching, used by the pipeline |
| `src/zkp_registry.py`, `src/zkp_sessions.py`, `src/lattice_pq.py` | ML-DSA-signed relation registry, one-use verifier sessions, ML-DSA/ML-KEM wrappers |
| `research/bdlop_params/` | Core-SVP parameter estimation (`estimate.py`, output `bdlop_open_128_v2.estimate.json`; v1: `bdlop_open_128.estimate.json`) and known-answer vectors (`kat.py`, `kat_v2.json`; v1: `kat_v1.json`) |
| `benchmark/latticezk_*.py`, `benchmark/latticezk_q2_cases.json` | Evaluation drivers: capacity scan, E2E, sweep, steganalysis, simulations, baselines, reports |
| `benchmark/results/q2/` | Results behind the paper (JSON, `SUMMARY.md`, `carrier_compare.md`) |
| `benchmark/results/latticezk_*_2026101*.json` | Earlier E2E, steganalysis and crypto-benchmark runs (2026-10-12/19) |
| `docs/paper/` | Manuscript; `tables/*.tex` and `figures/*.pdf` are generated |
| `scripts/` | Reproduction wrappers, `repro.py`, `data_manifest.json` (URLs and SHA-256 of all inputs) |
| `conftest.py`, `pytest.ini` | Skip tests whose gitignored local data is missing |
| `../.github/workflows/videolevel-latticezk.yml` | CI: the unit-test step on Ubuntu, Python 3.12 |

The video data is not in git (`data/` is ignored). Section 3 explains how to
get it.

## 2. Environment used for the reported numbers

| | |
|---|---|
| CPU | Intel Core i7-12700H, 14 cores / 20 threads |
| RAM | 24 GB (23.6 GiB visible to the OS) |
| GPU | RTX 3060 (not used by any step below) |
| OS | Windows 11 Pro 10.0.26100 |
| Python | 3.12.10 (CPython, `.venv312`) |
| FFmpeg | 8.0.1, gyan.dev "essentials" build, with libx264 core 165 r3223 0480cb0 |

Python packages: `requirements.lock` pins the direct dependencies. The full
environment (`pip freeze`) was:

```text
cffi==2.1.1  cloudpickle==3.1.2  colorama==0.4.6  contourpy==1.4.0  coverage==7.16.2
cryptography==50.0.1  cycler==0.12.1  fonttools==4.66.0  ImageIO==2.38.0  iniconfig==2.3.0
joblib==1.6.0  kiwisolver==1.5.1  lazy-loader==0.6  matplotlib==3.11.2  networkx==3.7
numpy==2.5.3  packaging==26.3  pillow==12.3.0  pluggy==1.6.0  pqcrypto==1.0.0  psutil==7.2.2
pycparser==3.0  Pygments==2.21.0  pyparsing==3.3.3  pytest==9.1.1  pytest-cov==7.1.0
python-dateutil==2.9.0.post0  scikit-image==0.26.0  scikit-learn==1.7.2  scipy==1.18.1
six==1.17.0  threadpoolctl==3.7.0  tifffile==2026.9.20
```

Install:

```bash
python -m venv .venv312                      # Python 3.12
.venv312/bin/python -m pip install -r requirements.lock     # Windows: .venv312\Scripts\python.exe
```

The wrappers use `.venv312` if it exists, otherwise `python3`/`python` (or
`py -3.12` on Windows). Set `PYTHON` (`$env:PYTHON` in PowerShell) to choose
another interpreter. `ffmpeg` and `ffprobe` must be on `PATH`; encoding needs
an FFmpeg build with libx264.

Timings depend on the machine. The CAVLC analysis is single-threaded pure
Python and takes up most of the embed and verify time; the proof itself takes
about 0.1 s to prove and 0.02 s to verify. The E2E numbers in
`benchmark/results/q2` were measured while two or three runs shared the
machine.

## 3. Data

### 3.1 Sources

All sequences come from the Xiph.org "derf" collection,
`https://media.xiph.org/video/derf/y4m/<file>`. Put them in `data/raw/`.

| File | URL | Frames | Bytes | SHA-256 |
|---|---|---:|---:|---|
| `akiyo_cif.y4m` | https://media.xiph.org/video/derf/y4m/akiyo_cif.y4m | 300 | 45 621 044 | `0f7a1f997930217d601ab324b1428859fdb599dde8d33772a24bfe2803a9b067` |
| `city_cif.y4m` | https://media.xiph.org/video/derf/y4m/city_cif.y4m | 300 | 45 621 038 | `2f99e08e66376c0a0acc9c7349aef7f61020be8fbfe6440bdb0c7ec7d05bb30f` |
| `coastguard_cif.y4m` | https://media.xiph.org/video/derf/y4m/coastguard_cif.y4m | 300 | 45 621 044 | `ae4052051ee9d77236ced5b231239dec97831c66faea3d7b70694e222ce00c43` |
| `container_cif.y4m` | https://media.xiph.org/video/derf/y4m/container_cif.y4m | 300 | 45 621 044 | `45abe3a99a0e2914742b3eecf474335362e31921bc0b30eef1dd45bb42df82be` |
| `deadline_cif.y4m` | https://media.xiph.org/video/derf/y4m/deadline_cif.y4m | 1374 | 208 944 224 | `4498852bf8f18d0c56957a4eff9611e3a851bfa9087e6ac8efffdadf2d02b964` |
| `football_cif.y4m` | https://media.xiph.org/video/derf/y4m/football_cif.y4m | 260 | 39 538 238 | `941d255821a877a4ed476cbeb8b9a2c0c6f72cfab86927afb5e355eb46a99956` |
| `hall_monitor_cif.y4m` | https://media.xiph.org/video/derf/y4m/hall_monitor_cif.y4m | 300 | 45 621 044 | `d0d4d6ebd137378bb5a7448c04d0cb73c20458a91d41d0f00cb090bd84bedd93` |
| `city_4cif.y4m` | https://media.xiph.org/video/derf/y4m/city_4cif.y4m | 600 | 364 957 238 | `06f9c001df816babf514a5713e8d4618233a217a39335e0810421a1519fd248e` |
| `crew_4cif.y4m` | https://media.xiph.org/video/derf/y4m/crew_4cif.y4m | 600 | 364 957 238 | `5faf4fc764a683ac1b97b5016ec940f61afa20c7a914fb80b5da82f6e9b04de1` |
| `harbour_4cif.y4m` | https://media.xiph.org/video/derf/y4m/harbour_4cif.y4m | 600 | 364 957 238 | `704c23e818baba916e28b83c193918c8e70ccc63ccf20d012017278402527950` |
| `soccer_4cif.y4m` | https://media.xiph.org/video/derf/y4m/soccer_4cif.y4m | 600 | 364 957 238 | `fb7f392cb7b4eb8bd3bc1de5b40b927237a98ca1a25aea509238ac949106438f` |
| `foreman_cif_300f.y4m` | none (see note) | 300 | 45 621 058 | `8594d27de626d4ed6d76883247796b185ab31c7695bf174eedab55bd0de1adb9` |

The hashes are those of the files the evaluation used, which were downloaded
from derf. The download was not repeated for this artifact (the build machine
had no network access), so the hashes have not been rechecked against the
server. If `--download` reports a mismatch, compare frame count and header
first: the server copy may have changed.

`foreman_cif_300f.y4m` is not a byte copy of the derf `foreman_cif.y4m` (its
header is `F10:1 A1:1 C420jpeg`) and the command that converted it was not
recorded. Only one capacity row (`capacity_seg0_foreman_q22.json`, Foreman
"cannot carry the envelope") depends on it, and the scripts treat it as
optional.

### 3.2 Encoding

All covers are x264 Baseline (CAVLC), all-intra, fixed QP:

```bash
ffmpeg -i data/raw/<clip>.y4m [-frames:v N] -c:v libx264 -profile:v baseline \
       -g 1 -bf 0 -qp <QP> -threads <T> -f h264 data/encoded/<clip>_q<QP>_g1.h264
```

`-threads` is 9 for CIF and 18 for 4CIF: these are the values x264 picked
automatically on the evaluation machine. x264 writes its option string,
thread count included, into an SEI NAL unit. With FFmpeg 8.0.1 / x264 r3223
and these thread counts the command reproduces the reference files byte for
byte. We checked this for 15 of the 16 covers that have a reference hash; the
exception is Foreman (see above). A different x264 build or thread count gives
the same decoded pixels for these all-intra encodes (we checked this for
Container with 4 and 9 threads), but the SEI bytes and the SHA-256 change.
Statement IDs may then differ too. Carrier positions and the measured
quantities should not, but that has not been tested.

Derived covers:

| Cover | Command difference | SHA-256 |
|---|---|---|
| `coastguard_cif_q22_g1_3000f.h264` | `-stream_loop 9` before `-i` (the 300-frame clip looped 10 times; say so when quoting it) | `68d70717...ead405` |
| `deadline_cif_q22_g1_1000f.h264` | `-frames:v 1000` | `ff35e477...ea072bd` |

`scripts/data_manifest.json` lists every cover, its source, QP, thread count
and full SHA-256. To check or create everything:

```bash
sh scripts/prepare_data.sh               # verify data/raw, encode missing covers, verify hashes
sh scripts/prepare_data.sh --download    # also fetch missing Y4M files (about 2.0 GB)
sh scripts/prepare_data.sh --strict-encoded   # fail instead of warn on a cover hash mismatch
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepare_data.ps1 --download
```

A wrong Y4M hash is always an error. A wrong cover hash is a warning unless
`--strict-encoded` is given. The Foreman cover is never an error, because its
mismatch is known. Time on the evaluation machine: about 5 s to hash the
sources and 35 s to encode all 18 covers.

## 4. How to run

### 4.1 Unit tests (about 90 s, no data needed)

```bash
sh scripts/run_unit_tests.sh                     # POSIX
powershell -ExecutionPolicy Bypass -File scripts\run_unit_tests.ps1   # Windows
```

The script checks that every file in `src/lattice_zk`,
`research/bdlop_params`, `benchmark` and `scripts` compiles. It then runs 23
pytest files (all `test_latticezk_*.py`, plus tests of the touched modules:
carrier analysis and the analysis cache, RBSP patching, chunk framing, blind
transport, sessions, session HTTP) and five script-style suites (lattice PQ
stack, relation registry, video ZKP statement contract, LaZer context
relation, fail-closed SIS prototype). It exits non-zero if any of them fails.
Some fixtures are synthesised with `ffmpeg` (libx264) at run time. One test reads a
gitignored cover and is skipped with a reason when the file is absent
(`conftest.py`, marker `needs_data`). CI runs the same script
(`.github/workflows/videolevel-latticezk.yml`).

Expected output on a clean checkout: `174 passed, 1 skipped` for pytest (v2 measurement pending), all
script suites `OK`, `RESULT: PASS`.

### 4.2 Known-answer vectors (about 10 s)

`src/runtest/test_latticezk_kat.py` (part of 4.1) regenerates the vectors and
compares them with `research/bdlop_params/kat_v1.json` and `kat_v2.json`. To
do it by hand for the production set:

```bash
mkdir -p tmp
python research/bdlop_params/kat.py --parameter-set BDLOP_OPEN_128_V2 --output tmp/kat_check.json
cmp tmp/kat_check.json research/bdlop_params/kat_v2.json      # Windows: fc /b; no output = identical
```

Checked for this artifact: the regenerated `kat_v1.json` is byte-identical
(8 s) (v2 measurement pending).

### 4.3 Parameter estimation (Table `tab:params`)

`estimate.py` uses the CRYSTALS security-estimates scripts at a pinned commit:

```bash
git clone https://github.com/pq-crystals/security-estimates
git -C security-estimates checkout 75c26949a902ca297b181375bfb7cfaf22cce784
python research/bdlop_params/estimate.py --estimator security-estimates \
       --parameter-set BDLOP_OPEN_128_V2 --output tmp/bdlop_open_128_v2.estimate.json
```

Compare the result with `research/bdlop_params/bdlop_open_128_v2.estimate.json`
(M-SIS binding 140/127 bits classical/quantum, M-LWE primal 169/153 bits). The
claimed hiding level, 164/150 bits, is the lattice-estimator's dual hybrid
(`research/bdlop_params/CROSSCHECK.md`).
`docs/paper/tables/params.tex` was transcribed by hand from that file. This
step was not rerun for the artifact because the build machine had no network
access.

### 4.4 Short end-to-end reproduction (10-15 min, < 2 GB RAM)

```bash
sh scripts/reproduce_small.sh            # default: first 100 frames of data/encoded/container_cif_q22_g1.h264
powershell -ExecutionPolicy Bypass -File scripts\reproduce_small.ps1
```

The script cuts the first 100 pictures of the cover at access-unit
boundaries; this is a byte prefix of the cover, so no re-encoding is
involved. It then runs `benchmark.latticezk_video_e2e` with the production
parameter set (`BDLOP_OPEN_128`) in registered mode. That run creates an
issuer key, a signed registry, a credential and a one-use session, embeds the
8 165-byte envelope, and verifies from the stego video alone. Finally the
script checks the report: production parameters, registered mode, expected
envelope size, verification succeeded, payload absent from the output. The
report, log and cut are written to `tmp/repro_small/run-<timestamp>/`.

Carrier choice: the registered envelope needs about 65.3 kbit. A 100-frame CIF
cut at QP 22 has 10-51 kbit of magnitude-LSB carriers but 470-550 kbit of
trailing-one sign carriers, so the short run uses `--carrier t1` with an
8 200-byte chunk (one segment). To exercise the default magnitude carrier,
use 200 frames: `--carrier magnitude --frames 200` (chunk 4 200 B; about
15 min). `--security-checks` also replays the consumed session and verifies a
copy with one flipped bit. Both must be rejected, and each check costs one
more full verification.

Reference run on the evaluation machine: see section 7.

### 4.5 Full reproduction (tens of hours)

```bash
sh scripts/reproduce_all.sh --workers 2            # resumable; add --download on a fresh machine
powershell -ExecutionPolicy Bypass -File scripts\reproduce_all.ps1 --workers 2
```

Steps, in order. A step is skipped if all its outputs already exist, so an
interrupted run resumes where it stopped:

| Step | Command (from `VideoLevel/`) | Output | Time on the evaluation machine |
|---|---|---|---|
| Data | `scripts/repro.py prepare-data` | `data/raw`, `data/encoded` | < 1 min (+ download) |
| Capacity, CIF | `python -m benchmark.latticezk_capacity_scan data/encoded/<clip>_cif_q<QP>_g1.h264 --output benchmark/results/q2/capacity_<clip>_q<QP>.json` (Akiyo, Deadline, Foreman: `--segments 1`, file `capacity_seg0_*`) | `capacity_*.json` | 2.7 h for the 10 scans |
| Sweep | `python -m benchmark.latticezk_q2_sweep --cases benchmark/latticezk_q2_cases.json --workers 2` | `e2e_*.json`, `steg_*.json`, `capacity_*_reg*.json`, `tmp/q2/mlfeat_*.npz`, stego videos in `tmp/q2/` | 25-35 CPU hours: 33 cases; the 19 recorded ones took 8-120 min each (14 h in total); 14 cases, mostly 4CIF density runs, have not run yet; about 15-20 h wall with 2 workers |
| In-band + linkage | `python -m benchmark.latticezk_video_e2e --video data/encoded/coastguard_cif_q22_g1_3000f.h264 --output tmp/q2/coastguard3000f_q22_inband_link.h264 --report benchmark/results/q2/e2e_coastguard3000f_q22_inband_link.json` | `e2e_coastguard3000f_q22_inband_link.json` | about 2 h |
| Learned steganalysis | `python -m benchmark.latticezk_ml_steganalysis evaluate tmp/q2/mlfeat_{city,coastguard,container,deadline,hall}_cif_q22_reg.npz --output benchmark/results/q2/ml_eval.json` | `ml_eval.json` | minutes |
| Rule simulation | `python -m benchmark.latticezk_embedding_sim --cases <the 5 CIF cases> --output benchmark/results/q2/embedding_t1_vs_magnitude_sim.json` | replacement / matching / T1 arms | < 1 h |
| Density simulation | same with `--densities 1 0.5 0.25 0.1 --output .../embedding_density_sim.json` | | < 1 h |
| Baselines | `python -m benchmark.latticezk_baselines --output benchmark/results/q2/baselines_<date>.json` | BDLOP, ML-DSA-44/65, Groth16 (needs `node`/`snarkjs` and `circuits/build`, otherwise recorded as an error), ISW21 (recorded, not rerun) | minutes |
| Crypto micro-benchmark | `python -m benchmark.latticezk_crypto_bench --runs 50 --output benchmark/results/latticezk_crypto_bench_<date>.json` | commit/prove/verify timings | minutes |
| Reports | `python -m benchmark.latticezk_q2_report`; `python -m benchmark.latticezk_carrier_compare --output benchmark/results/q2/carrier_compare.md`; `python -m benchmark.latticezk_density_report --output benchmark/results/q2/density_report.json` | `SUMMARY.md`, `docs/paper/tables/*.tex`, `docs/paper/figures/*.pdf` | seconds to minutes |

Resource limits: each E2E run uses 1-3 GB RAM. Run at most two or three
workers on a 24 GB machine. `--fresh` first moves `benchmark/results/q2` and
`tmp/q2` aside (to `*.bak-<timestamp>`; nothing is deleted) so that every step
reruns. Without it, committed results are kept and only missing ones are
produced. The report generators always read `benchmark/results/q2`.

Each report records the SHA-256 of its input cover (`input_video_sha256`) and
of the stego output. Comparing them with `scripts/data_manifest.json` shows
whether a rerun used the same covers. Stego bytes, statement IDs and timings
differ from run to run: every run draws fresh keys, a fresh session and a
fresh sync key.

## 5. Paper tables and figures

| Paper element | Produced by | Result file(s) |
|---|---|---|
| Table `tab:params` (parameters, core-SVP) | `research/bdlop_params/estimate.py` (4.3), transcribed | `research/bdlop_params/bdlop_open_128.estimate.json` -> `docs/paper/tables/params.tex` |
| Table `tab:capacity`, Figure `figures/capacity.pdf` | capacity scans + sweep, then `latticezk_q2_report` | `benchmark/results/q2/capacity_*.json` -> `tables/capacity.tex` |
| Table `tab:e2e`, Figure `figures/quality.pdf` | sweep (`latticezk_q2_sweep` -> `latticezk_video_e2e`), in-band step, then `latticezk_q2_report` | `benchmark/results/q2/e2e_*.json` -> `tables/e2e.tex` |
| Table `tab:steg-classical` | sweep (`latticezk_steganalysis`), then `latticezk_q2_report` | `benchmark/results/q2/steg_*.json` -> `tables/steg_classical.tex` |
| Table `tab:steg-ml` | sweep (`latticezk_ml_steganalysis features`), `... evaluate`, then `latticezk_q2_report` | `benchmark/results/q2/ml_eval.json` -> `tables/steg_ml.tex` |
| Section "Carrier choice" (Sec. `sec:carrier`) | `_t1` / `_t1_spread` sweep cases, `latticezk_carrier_compare` | `benchmark/results/q2/carrier_compare.md`, `e2e_*_t1*.json`, `capacity_*_reg_t1.json` |
| Section "Density" (Sec. `sec:density`), simulated | `latticezk_embedding_sim` | `benchmark/results/q2/embedding_density_sim.json`, `embedding_t1_vs_magnitude_sim.json` (`embedding_rule_sim.json` is the earlier two-arm run) |
| Section "Density", measured on 4CIF ("reported in the artifact") | `_d50` / `_d25` sweep cases, `latticezk_density_report` | `benchmark/results/q2/density_report.json`, `docs/paper/figures/density.pdf` (generated once the 4CIF density cases have run) |
| Table `tab:baselines` | `latticezk_baselines`, then `latticezk_q2_report` | `benchmark/results/q2/baselines_20261019.json` -> `tables/baselines.tex` |
| Prove/verify times in the text (0.12 s / 0.02 s, v1; v2 measurement pending) | `latticezk_crypto_bench` | `benchmark/results/latticezk_crypto_bench_20261012.json` |
| KAT (reproducibility of commitments and proofs) | `research/bdlop_params/kat.py` | `research/bdlop_params/kat_v2.json` (v1: `kat_v1.json`) |

`benchmark/results/q2/SUMMARY.md` collects the generated tables in Markdown.

## 6. Tests that need local data

The CI subset runs on a clean checkout. The only test in it that reads
gitignored data is
`test_video_only_blind_sync_integration.py::test_stego_video_alone_rederives_carriers_and_extracts_payload`
(needs `data/encoded/foreman_cif_g8_300f_b800k.h264`, a GOP-8 800 kbit/s
Foreman encode whose command is not recorded). It is skipped when the file is
absent. The older phase suites (`run_all.py` phases 2-7, 22, `test_e2e_sec1_verify.py`,
...) need the covers in `data/encoded/` and are not part of the lattice-ZK
artifact.

## 7. Reference run of `reproduce_small`

Measured with the earlier set `bdlop-open-128-v1` (v2 measurement pending).
Run on 2026-10-21 on the evaluation machine (other experiments were running at
the same time), with the defaults: the first 100 frames of
`container_cif_q22_g1.h264`, T1 carrier, chunk 8 000 B, and no security
checks.

| | |
|---|---|
| Cut cover SHA-256 | `84faaa9dba2f33f0452918de5eb586e58ecb8917acf472b9b13cdd7f9dd5d53a` (100 pictures, checked by ffprobe) |
| Parameter set / mode | `bdlop-open-128-v1`, registered commitment |
| Carrier contract | `t1-sign-video-only-v2` |
| Envelope / carriers / segments | 7 589 B / 61 008 / 1 |
| Verified from the stego video alone | yes (`ok`) |
| Payload in the output file | no |
| Luma PSNR, modified frames / worst frame | 42.60 dB / 39.24 dB (100 of 100 frames modified) |
| SSIM, whole video | 0.995689 |
| Embed / verify | 452 s / 293 s |
| Wall time, whole E2E process | 746 s (12.4 min) |
| Peak RSS (process tree) | 1 736 MiB |

Script output (paths shortened):

```text
[04:23:50] e2e exit code 0, wall 746 s, peak RSS 1736 MiB
  [PASS] production parameter set bdlop-open-128-v1
  [PASS] registered mode
  [PASS] envelope has the expected size
  [PASS] verified from the stego video alone
  [PASS] payload absent from the stego file
RESULT: PASS
```
