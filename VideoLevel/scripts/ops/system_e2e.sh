#!/usr/bin/env bash
# Functional end-to-end check of every system mode under bdlop-open-128-v2.
# Each scenario embeds, verifies from the stego video alone, and (by default)
# re-verifies a replayed session and a one-bit tampered copy, which must fail.
set -u
cd "$(dirname "$0")/.."
export ZKSTEGO_ANALYSIS_WORKERS=4  # 8 is the default; 4 leaves room for the IDE
PY=.venv312/Scripts/python.exe
W=tmp/system_e2e
mkdir -p "$W"
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$W/progress.txt"; }

cut() {  # all-intra, so a stream copy of the first N pictures is exact
  [ -e "$W/$2" ] || ffmpeg -hide_banner -loglevel error -y -i "data/encoded/$1" -frames:v "$3" -c copy "$W/$2"
}
cut container_cif_q22_g1.h264 container_100.h264 100
cut container_cif_q22_g1.h264 container_200.h264 200
cut container_cif_q22_g1.h264 container_300.h264 300
cut coastguard_cif_q22_g1.h264 coastguard_300.h264 300

run() {
  local name=$1 video=$2; shift 2
  if [ -e "$W/$name.json" ]; then say "skip  $name (report exists)"; return; fi
  say "start $name"
  local t0=$(date +%s)
  # A scenario that runs past 40 minutes is treated as hung and stopped.
  timeout 2400 $PY -B -m benchmark.latticezk_video_e2e --video "$video" --output "$W/$name.stego.h264" \
    --report "$W/$name.json" "$@" > "$W/$name.log" 2>&1
  say "end   $name exit=$? $(( ($(date +%s) - t0) / 60 )) min"
  rm -f "$W/$name.stego.h264"
}

run reg_magnitude      $W/container_200.h264  --registered --chunk-bytes 4200
run inband_magnitude   $W/container_300.h264  --chunk-bytes 5000
run reg_t1             $W/container_100.h264  --registered --carrier t1 --chunk-bytes 8200
run reg_stc            $W/container_200.h264  --registered --carrier adaptive --chunk-bytes 4200
run reg_adaptive_chunk $W/coastguard_300.h264 --registered --adaptive-chunks
run reg_codec_v2       $W/container_200.h264  --registered --chunk-bytes 4200 --codec-policy v2 --trailing-rbsp-check
run reg_gop8           tmp/gop128/container_g8_3000f_reg128.h264 --registered \
    --gop-policy idr-carriers-inter-raw-v1 --frames-per-segment 200 --chunk-bytes 1250

say "start unit_tests"
$PY -B scripts/repro.py unit-tests > "$W/unit_tests.log" 2>&1
say "end   unit_tests exit=$?"
say "ALL DONE"
