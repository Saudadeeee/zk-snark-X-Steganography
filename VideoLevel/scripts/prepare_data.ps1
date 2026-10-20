# Verify the Xiph Y4M sources in data\raw (SHA-256), optionally download the
# missing ones, then encode the covers into data\encoded and check their hashes.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\prepare_data.ps1 [--download] [--only NAME ...]
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
& $Python @PythonArgs -B scripts/repro.py prepare-data @args
exit $LASTEXITCODE
