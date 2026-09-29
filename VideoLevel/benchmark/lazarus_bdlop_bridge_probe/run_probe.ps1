$ErrorActionPreference = 'Stop'

$repository = 'https://github.com/lattice-complete/Lazarus.git'
$revision = '4363e5151a25dac2e96885cd08c1bdfb7ac3c1af'
$image = 'rustlang/rust@sha256:66726eb549e867024ed4b890cb133e7304b52cc2f380d425b7ce210849970894'
$checkout = Join-Path $env:TEMP ('lazarus-bdlop-bridge-' + [Guid]::NewGuid().ToString('N'))
$testSource = Join-Path $PSScriptRoot 'bdlop_opening_bridge_probe.rs'

git clone $repository $checkout
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git -C $checkout checkout --detach $revision
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$testDirectory = Join-Path $checkout 'labrador/tests'
New-Item -ItemType Directory -Path $testDirectory -Force | Out-Null
$testDestination = Join-Path $testDirectory 'bdlop_opening_bridge_probe.rs'
Copy-Item -LiteralPath $testSource -Destination $testDestination

$mountPath = $checkout.Replace('\', '/') + ':/work'
docker run --rm --volume $mountPath --workdir /work $image `
    cargo test -p labrador --test bdlop_opening_bridge_probe -- --nocapture
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Pinned probe checkout retained at: $checkout"
