# One registered end-to-end run with the production parameter set on the first
# 100 frames of a cover (default data\encoded\container_cif_q22_g1.h264):
# embed, verify from the stego video alone, check the report. About 10-15 min.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\reproduce_small.ps1 [--video FILE] [--frames N]
#        [--carrier t1|magnitude] [--security-checks] [--keep]
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
& $Python @PythonArgs -B scripts/repro.py small @args
exit $LASTEXITCODE
