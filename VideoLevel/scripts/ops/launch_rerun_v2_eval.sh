#!/usr/bin/env bash
cd /d/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel || exit 1
echo "launcher start $(date +%H:%M:%S) ffmpeg=$(command -v ffmpeg)" >> tmp/rerun_v2/launcher.txt
exec bash scripts/ops/rerun_v2_eval.sh > tmp/rerun_v2.out 2>&1
