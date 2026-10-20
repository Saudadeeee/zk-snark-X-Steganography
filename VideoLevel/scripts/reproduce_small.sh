#!/bin/sh
# One registered end-to-end run with the production parameter set on the first
# 100 frames of a cover (default data/encoded/container_cif_q22_g1.h264):
# embed, verify from the stego video alone, check the report. About 10-15 min.
# Usage: sh scripts/reproduce_small.sh [--video FILE] [--frames N] [--carrier t1|magnitude]
#                                      [--security-checks] [--keep]
set -u
. "$(dirname -- "$0")/_common.sh"
exec "$PYTHON" -B scripts/repro.py small "$@"
