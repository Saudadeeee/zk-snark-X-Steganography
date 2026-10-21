#!/usr/bin/env bash
cd /d/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel || exit 1
exec bash scripts/ops/system_e2e.sh > tmp/system_e2e.out 2>&1
