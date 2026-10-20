# The whole lattice-ZK evaluation: data preparation, capacity scans, the
# multi-clip sweep, learned steganalysis, simulations, baselines and report
# generation. Resumable; tens of CPU hours (see ARTIFACT.md section 6).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\reproduce_all.ps1 [--workers N] [--download] [--fresh]
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
& $Python @PythonArgs -B scripts/repro.py all @args
exit $LASTEXITCODE
