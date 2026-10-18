[CmdletBinding()]
param([string]$LLBotRoot = $env:LLBOT_ROOT, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
if (-not $LLBotRoot) {
    $settings = Join-Path $PSScriptRoot 'launcher.local.json'
    if (Test-Path -LiteralPath $settings) {
        $LLBotRoot = (Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json).LLBotRoot
    }
}
if (-not $LLBotRoot) { throw 'Run install.ps1 -LLBotRoot <directory> first, or specify -LLBotRoot.' }
$root = (Resolve-Path -LiteralPath $LLBotRoot).Path
$cli = Join-Path $root 'CLI'
$exe = Join-Path $cli 'llbot.exe'
$bridge = Join-Path $root 'AIBridge'
$python = Join-Path $bridge '.venv\Scripts\python.exe'
$entry = Join-Path $bridge 'bridge.py'
foreach ($file in @($exe, $python, $entry)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Missing: $file. Run install.ps1 first." }
}
function Get-Listener([int]$Port) {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
}
function Wait-Listener([int]$Port) {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Get-Listener $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}
function Assert-Owner([int]$Port, [string]$ExpectedDirectory, [string]$ExpectedScript = '') {
    $listener = Get-Listener $Port
    if (-not $listener) { return }
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess)
    $prefix = $ExpectedDirectory.TrimEnd('\') + '\'
    $owned = ($process.ExecutablePath -and $process.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase))
    if (-not $owned -and $ExpectedScript -and $process.Name -match '^python(?:w)?\.exe$') {
        $owned = $process.CommandLine -match ('(?:^|[\s"])' + [regex]::Escape($ExpectedScript) + '(?:[\s"]|$)')
    }
    if (-not $owned) { throw "Port $Port is occupied by another process (PID $($listener.OwningProcess)). No process was stopped." }
}
Assert-Owner 3080 $root
Assert-Owner 3001 $root
Assert-Owner 8001 $bridge $entry
if (-not (Get-Listener 3080)) {
    if (Get-Listener 3001) { throw 'OneBot is running without WebUI. Check the existing LLBot instance first.' }
    Start-Process -FilePath $exe -WorkingDirectory $cli -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $root 'llbot-launcher.out.log') `
        -RedirectStandardError (Join-Path $root 'llbot-launcher.err.log') | Out-Null
    if (-not (Wait-Listener 3080)) { throw 'LLBot WebUI did not start. Check llbot-launcher.err.log.' }
}
if (-not (Get-Listener 8001)) {
    Start-Process -FilePath $python -ArgumentList ('"{0}"' -f $entry) -WorkingDirectory $bridge -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $bridge 'launcher.out.log') `
        -RedirectStandardError (Join-Path $bridge 'launcher.err.log') | Out-Null
    if (-not (Wait-Listener 8001)) { throw 'Bridge did not start. Check AIBridge\launcher.err.log.' }
}
$health = Invoke-RestMethod 'http://127.0.0.1:8001/health' -TimeoutSec 5
if (-not $health.ok) { throw 'Bridge health check failed.' }
try {
    $connection = Invoke-RestMethod 'http://127.0.0.1:8001/api/test' -Method Post `
        -ContentType 'application/json' -Body '{"target":"onebot"}' -TimeoutSec 12
    if (-not $connection.success) { throw 'OneBot did not report success.' }
    Write-Host 'LLBot, bridge and OneBot connection are ready.' -ForegroundColor Green
} catch {
    Write-Warning 'Bridge is running. Log in to QQ and enable the OneBot WebSocket server on port 3001, then test OneBot in AI settings.'
}
Write-Host 'AI settings: http://127.0.0.1:3080/llbot-ai-config.html'
Write-Host 'Bridge health: http://127.0.0.1:8001/health'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:3080/llbot-ai-config.html' }
