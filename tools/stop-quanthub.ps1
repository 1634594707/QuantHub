[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PidFile = Join-Path $ProjectRoot 'logs\launcher\processes.json'

if (-not (Test-Path $PidFile)) {
    Write-Host "No launcher process record found: $PidFile"
    exit 0
}

$Started = Get-Content -Raw -Encoding UTF8 -LiteralPath $PidFile | ConvertFrom-Json
foreach ($ProcessId in @($Started.api_pid, $Started.web_pid)) {
    if (-not $ProcessId) { continue }
    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($Process) {
        Stop-Process -Id $ProcessId
        Write-Host "Stopped process $ProcessId ($($Process.ProcessName))"
    }
}

Remove-Item -LiteralPath $PidFile -Force
