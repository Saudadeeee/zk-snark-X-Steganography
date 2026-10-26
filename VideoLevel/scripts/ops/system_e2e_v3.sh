#!/usr/bin/env bash
# Functional end-to-end check of every system mode under bdlop-open-128-v3 with
# the current defaults (codec policy v2).  Each scenario embeds, verifies from
# the stego video alone, and re-verifies a replayed session and a one-bit
# tampered copy, which must fail.  Reports: tmp/system_e2e_v3/<name>.json.
#
#   bash scripts/ops/system_e2e_v3.sh            # all scenarios + unit tests
#   ZKSTEGO_ANALYSIS_WORKERS=2 bash scripts/ops/system_e2e_v3.sh
set -u
cd "$(dirname "$0")/../.."
export ZKSTEGO_ANALYSIS_WORKERS="${ZKSTEGO_ANALYSIS_WORKERS:-4}"
PY=${PY:-.venv312/Scripts/python.exe}
[ -x "$PY" ] || PY=python
W=tmp/system_e2e_v3
mkdir -p "$W"
say() { echo "$(date +%H:%M:%S) $*" | tee -a "$W/progress.txt"; }

cut() {  # all-intra, so a stream copy of the first N pictures is exact
  [ -e "$W/$2" ] || ffmpeg -hide_banner -loglevel error -y -i "data/encoded/$1" -frames:v "$3" -c copy "$W/$2"
}
cut container_cif_q22_g1.h264 container_100.h264 100
cut container_cif_q22_g1.h264 container_200.h264 200
cut container_cif_q22_g1.h264 container_300.h264 300
cut coastguard_cif_q22_g1.h264 coastguard_300.h264 300
cut coastguard_cif_q22_g1_3000f.h264 coastguard_1500.h264 1500

# GOP 8, 3000 pictures of looped Container (benchmark/latticezk_gop_cases.json,
# case container_g8_3000f_reg128; docs/GOP_HD_SUPPORT.md).
GOP8=$W/container_g8_3000f.h264
[ -e "$GOP8" ] || ffmpeg -hide_banner -nostdin -loglevel error -y -stream_loop 9 -i data/raw/container_cif.y4m \
  -frames:v 3000 -c:v libx264 -profile:v baseline -coder 0 -bf 0 -g 8 -keyint_min 8 -sc_threshold 0 \
  -qp 22 -threads 4 -f h264 "$GOP8"

run() {
  local name=$1 video=$2; shift 2
  if [ -e "$W/$name.json" ]; then say "skip  $name (report exists)"; return; fi
  say "start $name"
  local t0=$(date +%s)
  # A scenario that runs past 60 minutes is treated as hung and stopped.
  timeout 3600 $PY -B -m benchmark.latticezk_video_e2e --video "$video" --output "$W/$name.stego.h264" \
    --report "$W/$name.json" "$@" > "$W/$name.log" 2>&1
  say "end   $name exit=$? $(( ($(date +%s) - t0) / 60 )) min"
  rm -f "$W/$name.stego.h264"
}

# Defaults are bdlop-open-128-v3 and codec policy v2.
run reg_magnitude      $W/container_200.h264  --registered --chunk-bytes 4500 --trailing-rbsp-check
run inband_magnitude   $W/container_300.h264  --chunk-bytes 5500
run reg_t1             $W/container_100.h264  --registered --carrier t1 --chunk-bytes 8800
run reg_stc            $W/container_200.h264  --registered --carrier adaptive --chunk-bytes 4500
run reg_adaptive_chunk $W/coastguard_300.h264 --registered --adaptive-chunks
run reg_codec_v1       $W/container_200.h264  --registered --chunk-bytes 4500 --codec-policy v1
run reg_gop8           $GOP8 --registered --gop-policy idr-carriers-inter-raw-v1 \
    --frames-per-segment 200 --chunk-bytes 1250
# In-band envelope with the attached payload range proof (L = 32): 63 094 B.
# Coastguard carries ~31 kbit per 100-frame segment, so the adaptive transport
# spreads the envelope over ~17 segments of the 3 000-frame clip.
run inband_range32     data/encoded/coastguard_cif_q22_g1_3000f.h264 --adaptive-chunks --payload-range-bytes 32

say "start unit_tests"
$PY -B scripts/repro.py unit-tests > "$W/unit_tests.log" 2>&1
say "end   unit_tests exit=$?"
say "ALL DONE"
