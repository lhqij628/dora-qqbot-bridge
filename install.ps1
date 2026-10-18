[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$LLBotRoot,
    [string]$PythonCommand = 'python',
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $LLBotRoot).Path
$webRoot = Join-Path $root 'CLI\bin\llbot\webui'
$index = Join-Path $webRoot 'index.html'
if (-not (Test-Path -LiteralPath (Join-Path $root 'CLI\llbot.exe'))) {
    throw 'Expected CLI\llbot.exe in LLBotRoot. Install LLBot from its official site first.'
}
if (-not (Test-Path -LiteralPath $index)) { throw "LLBot WebUI not found: $index" }
$bridgeRoot = Join-Path $root 'AIBridge'
$sourceRoot = Join-Path $PSScriptRoot 'AIBridge'
if ([IO.Path]::GetFullPath($bridgeRoot).TrimEnd('\') -eq [IO.Path]::GetFullPath($sourceRoot).TrimEnd('\')) {
    throw 'Choose the LLBot installation directory, separate from this source checkout.'
}
$backup = Join-Path $root ('installation-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $bridgeRoot,$backup -Force | Out-Null
foreach ($name in @('bridge.py', 'requirements.txt', 'start-ai-bridge.ps1')) {
    $target = Join-Path $bridgeRoot $name
    if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination $target
}
$config = Join-Path $bridgeRoot 'config.json'
if (-not (Test-Path -LiteralPath $config)) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'config.example.json') -Destination $config
}
if (-not $SkipDependencies) {
    & $PythonCommand -c 'import sys; sys.exit(sys.version_info < (3, 10))'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
    $python = Join-Path $bridgeRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        & $PythonCommand -m venv (Join-Path $bridgeRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
    }
    & $python -m pip install -r (Join-Path $bridgeRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
foreach ($name in @('llbot-ai-config.html', 'llbot-ai-config.js')) {
    $target = Join-Path $webRoot $name
    if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "webui\$name") -Destination $target
}
$html = [IO.File]::ReadAllText($index)
if ($html -notmatch 'src\s*=\s*["'']/llbot-ai-config\.js(?:\?[^"'']*)?["'']') {
    if ($html -notmatch '(?i)</body\s*>') { throw 'WebUI index has no closing body tag.' }
    Copy-Item -LiteralPath $index -Destination (Join-Path $backup 'index.html')
    $html = [regex]::Replace($html, '(?i)</body\s*>', '<script src="/llbot-ai-config.js"></script></body>')
    [IO.File]::WriteAllText($index, $html, (New-Object Text.UTF8Encoding($false)))
}
@{ LLBotRoot = $root } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'launcher.local.json') -Encoding UTF8
Write-Host "Installed. Existing configuration and memory were preserved. Backups: $backup"
if ($SkipDependencies) { Write-Warning 'Dependencies skipped. Create AIBridge\.venv and install requirements before starting.' }
Write-Host 'Run start-qqbot-full.bat from this checkout. First login: http://127.0.0.1:3080'
