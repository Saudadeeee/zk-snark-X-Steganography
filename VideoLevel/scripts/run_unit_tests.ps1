# Run the lattice-ZK and touched-module tests (pytest + script-style suites).
# Needs no gitignored data; exits non-zero on any failure.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run_unit_tests.ps1 [--junit-xml FILE]
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
& $Python @PythonArgs -B scripts/repro.py unit-tests @args
exit $LASTEXITCODE
