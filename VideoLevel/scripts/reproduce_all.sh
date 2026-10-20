#!/bin/sh
# The whole lattice-ZK evaluation: data preparation, capacity scans, the
# multi-clip sweep, learned steganalysis, simulations, baselines and report
# generation. Resumable; tens of CPU hours (see ARTIFACT.md section 6).
# Usage: sh scripts/reproduce_all.sh [--workers N] [--download] [--fresh] [--skip-prepare]
set -u
. "$(dirname -- "$0")/_common.sh"
exec "$PYTHON" -B scripts/repro.py all "$@"
