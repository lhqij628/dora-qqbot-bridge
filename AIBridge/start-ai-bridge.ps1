$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Virtual environment missing. Run install.ps1 first.'
}
Push-Location $PSScriptRoot
try {
    & $python (Join-Path $PSScriptRoot 'bridge.py')
    if ($LASTEXITCODE -ne 0) { throw "Bridge exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
