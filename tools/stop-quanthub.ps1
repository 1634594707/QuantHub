[CmdletBinding()]
param(
    # Tear down by port even when no launcher record exists (crash recovery).
    [switch]$Force
)

# M1-05: stop Web + API + headless OKX Runner. The Runner is stopped first so the
# API never forwards trading calls to a half-closed Runner.
# Idempotent: missing processes are skipped, and running twice is a no-op.
# Two-stage teardown:
#   1) stop the PIDs recorded by start-quanthub.ps1;
#   2) if the port is still listening, stop whoever owns it. This covers the
#      npm.cmd wrapper case, where the recorded PID is the wrapper and the real
#      listener is a child node process.
# Keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI).
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$WebRoot = Join-Path $ProjectRoot 'web'
$PidFile = Join-Path $ProjectRoot 'logs\launcher\processes.json'

$DefaultPorts = [ordered]@{ runner = 8103; api = 8001; web = 5173 }

function Get-PortOwnerPid {
    param([int]$Port)
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -First 1
        if ($connection) { return [int]$connection.OwningProcess }
    } catch {
        $line = netstat -ano -p TCP |
            Select-String -Pattern 'LISTENING' |
            Select-String -Pattern ":$Port\s" |
            Select-Object -First 1
        if ($line) {
            $fields = ($line.ToString().Trim() -split '\s+')
            $candidate = $fields[-1]
            if ($candidate -match '^\d+$') { return [int]$candidate }
        }
    }
    return $null
}

function Stop-ByPid {
    param($TargetPid, [string]$Label, [string]$Kind, [int]$Port = 0)
    if (-not $TargetPid) { return $false }
    $resolved = [int]$TargetPid
    if ($resolved -le 0) { return $false }
    $process = Get-Process -Id $resolved -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    if ($Kind -and -not (Test-QuantHubProcess -ProcessId $resolved -Kind $Kind -Port $Port)) {
        Write-Warning "Skipping $Label process $resolved ($($process.ProcessName)): not a QuantHub $Kind process."
        return $false
    }
    Stop-Process -Id $resolved -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $Label process $resolved ($($process.ProcessName))"
    return $true
}

function Stop-ByPort {
    param([int]$Port, [string]$Label, [string]$Kind)
    if ($Port -le 0) { return $false }
    $owner = Get-PortOwnerPid -Port $Port
    if (-not $owner) { return $false }
    return (Stop-ByPid -TargetPid $owner -Label "$Label (port $Port)" -Kind $Kind -Port $Port)
}

# Verify a PID actually belongs to a QuantHub component before terminating it, so an
# unrelated process on the same port is never killed.
function Get-ProcessCommandLine {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $null }
    try {
        $proc = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine) { return $proc.CommandLine }
    } catch {}
    return $null
}

# Probe the dev server for the QuantHub page title (fallback web identity).
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

# Probe the service health endpoint (fallback api/runner identity).
function Test-QuantHubServiceHealth {
    param([int]$Port, [string]$Kind)
    if ($Port -le 0) { return $false }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 -ErrorAction Stop
        if ($Kind -eq 'api') { return ($health.status -eq 'ok' -and $health.build_id) }
        if ($Kind -eq 'runner') { return ($null -ne $health) }
        return $false
    } catch {
        return $false
    }
}

function Test-QuantHubProcess {
    param([int]$ProcessId, [string]$Kind, [int]$Port = 0)
    $cmd = Get-ProcessCommandLine -ProcessId $ProcessId
    if ([string]::IsNullOrWhiteSpace($cmd)) { return $false }
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
        'api' {
            # Module string 'apps.api.main' is project-specific; the health probe is a
            # second gate in case a port is held by an unrelated uvicorn.
            if (($norm -match 'uvicorn') -and ($norm -match 'apps\.api\.main')) { return $true }
            if ($Port -gt 0 -and (Test-QuantHubServiceHealth -Port $Port -Kind 'api')) { return $true }
            return $false
        }
        'runner' {
            if (($norm -match 'uvicorn') -and ($norm -match 'apps\.okx_runner\.main')) { return $true }
            if ($Port -gt 0 -and (Test-QuantHubServiceHealth -Port $Port -Kind 'runner')) { return $true }
            return $false
        }
        default  { return $false }
    }
}

$Started = $null
if (Test-Path -LiteralPath $PidFile) {
    try {
        $Started = Get-Content -Raw -Encoding UTF8 -LiteralPath $PidFile | ConvertFrom-Json
    } catch {
        Write-Warning "Launcher record is unreadable; falling back to default ports."
    }
} else {
    Write-Host "No launcher process record found: $PidFile"
    if (-not $Force) {
        Write-Host "Nothing recorded to stop. Re-run with -Force to tear down by port."
        exit 0
    }
}

# Runner first, then API, then Web. Each target carries a Kind so the teardown
# only stops processes that are actually QuantHub components.
$Targets = @(
    @{ Label = 'runner'; Pid = $(if ($Started) { $Started.runner_pid } else { $null }); Port = $(if ($Started -and $Started.runner_port) { [int]$Started.runner_port } else { $DefaultPorts.runner }); Kind = 'runner' },
    @{ Label = 'api';    Pid = $(if ($Started) { $Started.api_pid }    else { $null }); Port = $(if ($Started -and $Started.api_port)    { [int]$Started.api_port }    else { $DefaultPorts.api }); Kind = 'api' },
    @{ Label = 'web';    Pid = $(if ($Started) { $Started.web_pid }    else { $null }); Port = $(if ($Started -and $Started.web_port)    { [int]$Started.web_port }    else { $DefaultPorts.web }); Kind = 'web' }
)

$StoppedAny = $false
foreach ($target in $Targets) {
    $stopped = Stop-ByPid -TargetPid $target.Pid -Label $target.Label -Kind $target.Kind -Port $target.Port
    # The recorded PID may be a wrapper; make sure the port is actually released,
    # but only stop a port owner that is genuinely a QuantHub component.
    if (Stop-ByPort -Port $target.Port -Label $target.Label -Kind $target.Kind) { $stopped = $true }
    if ($stopped) {
        $StoppedAny = $true
    } else {
        Write-Host "$($target.Label): nothing running (port $($target.Port))"
    }
}

if (Test-Path -LiteralPath $PidFile) {
    Remove-Item -LiteralPath $PidFile -Force
    Write-Host "Removed launcher record: $PidFile"
}

if (-not $StoppedAny) {
    Write-Host "QuantHub was already stopped."
}
