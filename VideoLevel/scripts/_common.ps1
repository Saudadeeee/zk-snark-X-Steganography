# Dot-sourced by the PowerShell wrappers: cd to VideoLevel\ and pick an interpreter.
# Override the interpreter with $env:PYTHON = "C:\path\to\python.exe".
$VideoLevel = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $VideoLevel
$Python = $env:PYTHON
$PythonArgs = @()
if (-not $Python) {
    foreach ($candidate in @(".venv312\Scripts\python.exe", ".venv\Scripts\python.exe", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { $Python = $candidate; break }
    }
}
if (-not $Python -and (Get-Command "py" -ErrorAction SilentlyContinue)) {
    $Python = "py"
    $PythonArgs = @("-3.12")
}
if (-not $Python) {
    Write-Error "no Python interpreter found; set `$env:PYTHON"
    exit 1
}
if ($Python -like ".venv*") { $Python = Join-Path $VideoLevel $Python }
$env:PYTHONUTF8 = "1"
