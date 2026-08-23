# QuantHub unified launcher (work package M1-05).
#
# One command starts three processes: Web (5173), unified API (8001)
# and the headless OKX Runner (8103).
# The Runner starts in the 'shadow' environment (read-only, never places orders).
# Pass -Demo to use the local OKX Demo vault. Live still requires
# QH_RUNNER_ENVIRONMENT=live plus QH_RUNNER_LIVE_APPROVED=1 and is never set here.
# Re-running is idempotent: a port already served by this project is left alone,
# and the PID recorded for that service is preserved (adopted from the previous
# run record, or discovered from the listening port) so stop-quanthub.ps1 can
# still tear it down. A re-run never overwrites a live PID with null.
#
# Keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# so non-ASCII comments corrupt the parse.
[CmdletBinding()]
param(
    [switch]$SkipSync,
    # Start only Web + API and leave the Runner down (research / read-only use).
    [switch]$SkipRunner,
    # Explicitly start the gateway and Runner in OKX Demo trading mode.
    [switch]$Demo
)

$ErrorActionPreference = 'Stop'
if ($Demo) {
    $env:QH_RUNNER_ENVIRONMENT = 'demo'
    $env:QH_OKX_CREDENTIAL_SOURCE = 'local_vault'
    $env:QUANTHUB_FACTOR_AUTO_DISCOVERY = '1'
    if (-not $env:QH_RUNNER_AUTH_TOKEN) {
        $env:QH_RUNNER_AUTH_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    }
}
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

function Get-PortOwnerPid {
    # Resolve the PID that currently listens on a local TCP port.
    # Used so a re-run can adopt processes started by an earlier run.
    param([int]$Port)
    $connection = $null
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
    } catch {
        # Get-NetTCPConnection is missing on some SKUs; fall back to netstat.
    }
    if ($connection) { return [int]$connection.OwningProcess }

    # Some Windows environments return an empty collection even when a port is
    # listening (for example, when the connection view is restricted). In that
    # case use netstat as the fallback as well.
    $line = netstat -ano -p TCP |
        Select-String -Pattern 'LISTENING' |
        Select-String -Pattern ":$Port\s" |
        Select-Object -First 1
    if ($line) {
        $fields = ($line.ToString().Trim() -split '\s+')
        $candidate = $fields[-1]
        if ($candidate -match '^\d+$') { return [int]$candidate }
    }
    return $null
}

function Resolve-ServicePid {
    # M1-05 idempotency: prefer the process that owns the listening port.
    # npm.cmd and uv are wrappers which can remain alive while a child process
    # owns the socket; persisting the wrapper PID breaks identity checks on a
    # repeated start and makes teardown depend on an extra port lookup.
    param([int]$Port, $PreviousPid)
    $owner = Get-PortOwnerPid -Port $Port
    if ($owner -and (Get-Process -Id $owner -ErrorAction SilentlyContinue)) {
        return [int]$owner
    }
    if ($PreviousPid) {
        $previous = [int]$PreviousPid
        if (Get-Process -Id $previous -ErrorAction SilentlyContinue) { return $previous }
    }
    return $null
}

# Verify a PID actually belongs to a QuantHub component before adopting it, so an
# unrelated process listening on the same port is never taken over.
function Get-ProcessCommandLine {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $null }
    try {
        $proc = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine) { return $proc.CommandLine }
    } catch {}
    return $null
}

# Probe the dev server for the QuantHub page title as a fallback identity signal,
# so a vite dev server from another project on the same port is rejected.
function Test-QuantHubWebMarker {
    param([int]$Port)
    if ($Port -le 0) { return $false }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return ($resp.Content -match 'QuantHub')
    } catch {
        return $false
    }
}

function Test-QuantHubProcess {
    param([int]$ProcessId, [string]$Kind, [int]$Port = 0)
    $cmd = Get-ProcessCommandLine -ProcessId $ProcessId
    # WMI process command lines may be inaccessible under a restricted token.
    # For the web server, the page marker is a sufficient identity signal.
    if ([string]::IsNullOrWhiteSpace($cmd)) {
        if ($Kind -eq 'web' -and $Port -gt 0) {
            return (Test-QuantHubWebMarker -Port $Port)
        }
        return $false
    }
    # Normalize to forward slashes so Windows backslash paths match reliably.
    $norm = $cmd.Replace('\', '/')
    $webRoot = $WebRoot.Replace('\', '/')
    switch ($Kind) {
        'web' {
            # Generic 'vite' is not enough: another project's vite on 5173 must be
            # rejected. Require the command line to reference THIS project's web dir,
            # or the port to serve the QuantHub page marker.
            if ($norm -notmatch 'vite') { return $false }
            if ($norm -like "*$webRoot*") { return $true }
            if ($Port -gt 0 -and (Test-QuantHubWebMarker -Port $Port)) { return $true }
            return $false
        }
        'api'    { return ($norm -match 'uvicorn') -and ($norm -match 'apps\.api\.main') }
        'runner' { return ($norm -match 'uvicorn') -and ($norm -match 'apps\.okx_runner\.main') }
        default  { return $false }
    }
}

# Load the previous run record so an already-running service keeps its PID.
$Previous = $null
if (Test-Path -LiteralPath $PidFile) {
    try {
        $Previous = Get-Content -Raw -Encoding UTF8 -LiteralPath $PidFile | ConvertFrom-Json
    } catch {
        Write-Warning "Existing $PidFile is unreadable; falling back to port discovery."
        $Previous = $null
    }
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
    # Adopt the running API instead of recording a null PID (M1-05 idempotency).
    $ApiPid = Resolve-ServicePid -Port 8001 -PreviousPid $Previous.api_pid
    $ApiState = 'already-running'
    $Health = $ExistingHealth
} else {
    $ApiProcess = Start-Process -FilePath $UvCommand -ArgumentList @('run', 'uvicorn', 'apps.api.main:app', '--host', '127.0.0.1', '--port', '8001') -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogRoot 'api.out.log') -RedirectStandardError (Join-Path $LogRoot 'api.err.log') -WindowStyle Hidden -PassThru
    $ApiPid = $ApiProcess.Id
    $ApiState = 'started'
    $Health = Wait-ForHealth 60
}

if (Test-Port 5173) {
    $Candidate = Resolve-ServicePid -Port 5173 -PreviousPid $Previous.web_pid
    if (-not $Candidate -or -not (Test-QuantHubProcess -ProcessId $Candidate -Kind 'web' -Port 5173)) {
        throw 'Port 5173 is used by a non-QuantHub process (not a vite dev server). Action: release port 5173 and retry.'
    }
    $WebPid = $Candidate
    $WebState = 'already-running'
} else {
    $WebProcess = Start-Process -FilePath $NpmCommand -ArgumentList @('run', 'dev') -WorkingDirectory $WebRoot -RedirectStandardOutput (Join-Path $LogRoot 'web.out.log') -RedirectStandardError (Join-Path $LogRoot 'web.err.log') -WindowStyle Hidden -PassThru
    $WebState = 'started'
    Wait-ForPort -Port 5173 -TimeoutSeconds 60 -Name 'Web app'
    $WebPid = Resolve-ServicePid -Port 5173 -PreviousPid $WebProcess.Id
    if (-not $WebPid -or -not (Test-QuantHubProcess -ProcessId $WebPid -Kind 'web' -Port 5173)) {
        throw 'Web app started, but its listening process could not be identified as this QuantHub Vite server.'
    }
}

# --- Headless OKX Runner (M1-05) -------------------------------------------
# The Runner binds 127.0.0.1 only. Browsers never reach it directly; the Web app
# always goes through the unified API at /api/trading/*.
$RunnerPort = if ($env:QH_RUNNER_PORT) { [int]$env:QH_RUNNER_PORT } else { 8103 }
$RunnerEnvironment = if ($env:QH_RUNNER_ENVIRONMENT) { $env:QH_RUNNER_ENVIRONMENT } else { 'shadow' }
$RunnerPid = $null
$RunnerState = 'skipped'

if (-not $SkipRunner) {
    if (Test-Port $RunnerPort) {
        try {
            $ExistingRunner = Invoke-RestMethod -Uri "http://127.0.0.1:$RunnerPort/health" -TimeoutSec 3
        } catch {
            throw "Port $RunnerPort is used by a non-QuantHub service. Action: release the port or pass -SkipRunner."
        }
        if (-not $ExistingRunner) {
            throw "Port $RunnerPort did not return a valid Runner health response. Action: release the port and retry."
        }
        $RunnerPid = Resolve-ServicePid -Port $RunnerPort -PreviousPid $Previous.runner_pid
        $RunnerState = 'already-running'
    } else {
        $env:QH_RUNNER_HOST = '127.0.0.1'
        $env:QH_RUNNER_PORT = "$RunnerPort"
        $env:QH_RUNNER_ENVIRONMENT = $RunnerEnvironment
        $RunnerProcess = Start-Process -FilePath $UvCommand -ArgumentList @('run', 'uvicorn', 'apps.okx_runner.main:app', '--host', '127.0.0.1', '--port', "$RunnerPort") -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $LogRoot 'runner.out.log') -RedirectStandardError (Join-Path $LogRoot 'runner.err.log') -WindowStyle Hidden -PassThru
        Wait-ForPort -Port $RunnerPort -TimeoutSeconds 60 -Name 'OKX Runner'
        $RunnerPid = $RunnerProcess.Id
        $RunnerState = 'started'
    }
} elseif ($Previous -and $Previous.runner_pid) {
    # -SkipRunner must not orphan a Runner started by an earlier run.
    $RunnerPid = Resolve-ServicePid -Port $RunnerPort -PreviousPid $Previous.runner_pid
    if ($RunnerPid) { $RunnerState = 'left-running' }
}

# Ports are persisted so the stop script can fall back to port ownership when a
# recorded PID is a wrapper (npm.cmd) or has already exited.
@{
    api_pid = $ApiPid
    api_port = 8001
    api_state = $ApiState
    web_pid = $WebPid
    web_port = 5173
    web_state = $WebState
    runner_pid = $RunnerPid
    runner_port = $RunnerPort
    runner_environment = if ($SkipRunner) { $null } else { $RunnerEnvironment }
    runner_state = $RunnerState
    first_started_at = if ($Previous -and $Previous.first_started_at) { $Previous.first_started_at } else { (Get-Date).ToString('o') }
    started_at = (Get-Date).ToString('o')
    build_id = $Health.build_id
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

Write-Host "QuantHub is ready: http://127.0.0.1:5173"
Write-Host "API build_id: $($Health.build_id)"
Write-Host "API: $ApiState (pid $ApiPid, port 8001)"
Write-Host "Web: $WebState (pid $WebPid, port 5173)"
Write-Host "OKX Runner: $RunnerState (pid $RunnerPid, port $RunnerPort, environment $RunnerEnvironment)"
Write-Host "Logs: $LogRoot"
