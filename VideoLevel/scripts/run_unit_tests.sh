#!/bin/sh
# Run the lattice-ZK and touched-module tests (pytest + script-style suites).
# Needs no gitignored data; exits non-zero on any failure.
# Usage: sh scripts/run_unit_tests.sh [--junit-xml FILE]
set -u
. "$(dirname -- "$0")/_common.sh"
exec "$PYTHON" -B scripts/repro.py unit-tests "$@"
