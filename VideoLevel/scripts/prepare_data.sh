#!/bin/sh
# Verify the Xiph Y4M sources in data/raw (SHA-256), optionally download the
# missing ones, then encode the covers into data/encoded and check their hashes.
# Usage: sh scripts/prepare_data.sh [--download] [--only NAME ...] [--strict-encoded]
set -u
. "$(dirname -- "$0")/_common.sh"
exec "$PYTHON" -B scripts/repro.py prepare-data "$@"
