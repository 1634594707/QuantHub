[CmdletBinding()]
param(
    [switch]$SkipSync
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$WebRoot = Join-Path $ProjectRoot 'web'
$LogRoot = Join-Path $ProjectRoot 'logs\launcher'
$PidFile = Join-Path $LogRoot 'processes.json'
$UvCache = Join-Path $ProjectRoot '.uv-cache'

# Windows treats environment keys case-insensitively, while some launchers provide both PATH and Path.
$ProcessPath = $env:Path
[Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[Environment]::SetEnvironmentVariable('Path', $ProcessPath, 'Process')

function Require-Command {
    param([string]$Name, [string]$InstallAction)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Missing $Name. Action: $InstallAction"
    }
    return $command.Source
}

function Test-Port {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-ForHealth {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 2
            if ($health.status -eq 'ok' -and $health.build_id) { return $health }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "API was not ready within ${TimeoutSeconds}s. Check $LogRoot\api.err.log and $LogRoot\api.out.log"
}

function Wait-ForPort {
    param([int]$Port, [int]$TimeoutSeconds, [string]$Name)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not listen on port $Port within ${TimeoutSeconds}s. Check $LogRoot\web.err.log and $LogRoot\web.out.log"
}

$UvCommand = Require-Command 'uv' 'Install uv and run this script again.'
$NodeCommand = Require-Command 'node' 'Install Node.js 18 or newer and run this script again.'
$NpmCommand = Require-Command 'npm.cmd' 'Install Node.js with npm and run this script again.'

$NodeVersionText = & $NodeCommand --version
$NodeVersion = [version]($NodeVersionText.TrimStart('v'))
if ($NodeVersion.Major -lt 18) {
    throw "Node.js is $NodeVersionText. Action: upgrade to Node.js 18 or newer."
}

New-Item -ItemType Directory -Force -Path $LogRoot, $UvCache | Out-Null
$env:UV_CACHE_DIR = $UvCache

if (-not $SkipSync) {
    Write-Host 'Checking Python dependencies...'
    & $UvCommand sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed. Action: inspect the uv output and network, then retry.' }
    if (-not (Test-Path (Join-Path $WebRoot 'node_modules'))) {
        Write-Host 'Installing frontend dependencies...'
        & $NpmCommand install --prefix $WebRoot
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed. Action: inspect the npm output and network, then retry.' }
    }
}

$PythonVersion = & $UvCommand run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($PythonVersion -notin @('3.11', '3.12')) {
    throw "Python is $PythonVersion. Action: run uv python install 3.11 and retry."
}
$SourceBuildId = & $UvCommand run python -c "from apps.api.main import SOURCE_BUILD_ID; print(SOURCE_BUILD_ID)"
if (-not $SourceBuildId) {
    throw 'Could not calculate the current API build_id. Action: inspect the Python import error and retry.'
}

if (Test-Port 8001) {
    try {
        $ExistingHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -TimeoutSec 3
    } catch {
        throw 'Port 8001 is used by a non-QuantHub service. Action: release port 8001 and retry.'
    }
    if ($ExistingHealth.status -ne 'ok' -or -not $ExistingHealth.build_id) {
        throw 'Port 8001 did not return a valid QuantHub health response. Action: release port 8001 and retry.'
    }
    if ($ExistingHealth.build_id -ne $SourceBuildId) {
        throw "Port 8001 runs build_id $($ExistingHealth.build_id), but the current source is $SourceBuildId. Action: stop the old API process and retry."
    }
    $ApiProcess = $null
    $Health = $ExistingHealth
} else {
    $ApiProcess = Start-Process -FilePath $UvCommand -ArgumentList @('run', 'uvicorn', 'apps.api.main:app', '--host', '127.0.0.1', '--port', '8001') -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogRoot 'api.out.log') -RedirectStandardError (Join-Path $LogRoot 'api.err.log') -WindowStyle Hidden -PassThru
    $Health = Wait-ForHealth 60
}

if (Test-Port 5173) {
    $WebProcess = $null
} else {
    $WebProcess = Start-Process -FilePath $NpmCommand -ArgumentList @('run', 'dev') -WorkingDirectory $WebRoot -RedirectStandardOutput (Join-Path $LogRoot 'web.out.log') -RedirectStandardError (Join-Path $LogRoot 'web.err.log') -WindowStyle Hidden -PassThru
    Wait-ForPort -Port 5173 -TimeoutSeconds 60 -Name 'Web app'
}

@{
    api_pid = if ($ApiProcess) { $ApiProcess.Id } else { $null }
    web_pid = if ($WebProcess) { $WebProcess.Id } else { $null }
    started_at = (Get-Date).ToString('o')
    build_id = $Health.build_id
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

Write-Host "QuantHub is ready: http://127.0.0.1:5173"
Write-Host "API build_id: $($Health.build_id)"
Write-Host "Logs: $LogRoot"
