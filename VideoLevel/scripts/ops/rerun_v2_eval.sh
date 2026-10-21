#!/usr/bin/env bash
# Re-run of the evaluation under bdlop-open-128-v2.
# Learned steganalysis (ML features, FLD evaluation, simulations, CNN) is deferred:
# ZKSTEGO_SKIP_LEARNED=1, and the v1 learned results stay in benchmark/results/q2.
# The HD sweep runs separately after the HD embedding-order fix.
# Each step logs to tmp/rerun_v2/<step>.log; a failing step does not stop the run.
set -u
cd "$(dirname "$0")/.."
export ZKSTEGO_SKIP_LEARNED=1
# Two analysis workers: eight (the default) peak near 7 GB on 4CIF, too much next to an IDE and agents.
export ZKSTEGO_ANALYSIS_WORKERS=2
PY=.venv312/Scripts/python.exe
R=benchmark/results/q2
LOG=tmp/rerun_v2
mkdir -p "$LOG" tmp/b1v2/cuts

say() { echo "$(date +%H:%M:%S) $*" | tee -a "$LOG/progress.txt"; }
step() {
  local name=$1; shift
  say "start $name"
  local t0=$(date +%s)
  "$@" > "$LOG/$name.log" 2>&1
  local code=$?
  say "end   $name exit=$code $(( ($(date +%s) - t0) / 60 )) min"
}

# 1. Sweep (all cases, one at a time: two 4CIF cases exceed 24 GB with the IDE open), in-band + linkage, baselines, crypto bench, reports.
step repro_all $PY -B scripts/repro.py all --skip-prepare --workers 1

# 2. GOP > 1 with the production envelope.
step gop128 env ZKSTEGO_ANALYSIS_WORKERS=2 $PY -B -m benchmark.latticezk_gop_eval \
  --cases benchmark/latticezk_gop_cases.json --work tmp/gop128_v2 \
  --only container_g8_3000f_reg128 coastguard_g8_3000f_reg128 container_g25_6000f_reg128

# 3. Syndrome-trellis carriers (B1): E2E only (changes, PSNR, verification).
for clip in container coastguard deadline; do
  [ -e tmp/b1v2/cuts/${clip}_200.h264 ] || ffmpeg -hide_banner -loglevel error -y \
    -i data/encoded/${clip}_cif_q22_g1.h264 -frames:v 200 -c copy tmp/b1v2/cuts/${clip}_200.h264
done
step adaptive_e2e env ZKSTEGO_ANALYSIS_WORKERS=2 $PY -B -m benchmark.latticezk_adaptive_e2e \
  --covers tmp/b1v2/cuts/container_200.h264 tmp/b1v2/cuts/coastguard_200.h264 tmp/b1v2/cuts/deadline_200.h264 \
  --work tmp/b1v2/work --output $R/adaptive_e2e_v2.json

# 4. Binary proof benchmark.
step binary_bench $PY -B -m benchmark.latticezk_binary_proof_bench --runs 20 --output $R/binary_proof_bench.json

# 5. Timings on an idle host (the sweep ran two cases at a time).
step idle_timing env -u ZKSTEGO_ANALYSIS_WORKERS $PY -B -m benchmark.latticezk_idle_timing --cases container_cif_q22_reg coastguard_cif_q22_reg city4cif_q22_reg harbour4cif_q22_reg coastguard3000f_q22_reg container_cif_q22_reg_t1_spread container_cif_q22_reg_t1v2_spread

# 6. Reports.
step density_report $PY -B -m benchmark.latticezk_density_report --output $R/density_report.json
step q2_report $PY -B -m benchmark.latticezk_q2_report
step make_tables $PY -B docs/paper/tools/make_tables.py
say "ALL DONE"
