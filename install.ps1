# ==============================================================================
# Public Intelligence - One-Click Windows Host Node Installer (PowerShell)
# ==============================================================================
param(
    # This project operates NO network. bootstrap.public-intelligence.net is NXDOMAIN
    # and the hosted Scheduler does not answer, yet both were written into every .env
    # this script generated -- so the happy path produced a node that connected to
    # nothing, slowly. See docs/decisions/D6-is-there-a-network.md and ROADMAP C1.
    #
    # 8000 is the Scheduler's port. Reaching another network is now an explicit
    # -BootstrapRouter, because it always was a decision and used to be a hidden one.
    [string]$SchedulerUrl = $(if ($env:SCHEDULER_URL) { $env:SCHEDULER_URL } else { "http://localhost:8000" }),
    [string[]]$BootstrapRouter = @()
)

$ErrorActionPreference = "Stop"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "          Public Intelligence Decentralized Compute Node Installer (Windows)   " -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[INFO] Detecting Windows system hardware capabilities..." -ForegroundColor Blue

# Hardware discovery
$OS = (Get-CimInstance Win32_OperatingSystem).Caption
$CPU = (Get-CimInstance Win32_Processor).Name
$Cores = (Get-CimInstance Win32_Processor).NumberOfLogicalProcessors
$RAM_Bytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
$RAM_GB = [math]::Round($RAM_Bytes / 1GB, 2)

$GPU_Obj = Get-CimInstance Win32_VideoController | Select-Object -First 1
$GPU_Name = if ($GPU_Obj) { $GPU_Obj.Name } else { "Generic Display Adapter" }

Write-Host "[OK] Hardware Auto-Discovery Results:" -ForegroundColor Green
Write-Host "[OK]   - Operating System  : $OS" -ForegroundColor Green
Write-Host "[OK]   - CPU Model         : $CPU ($Cores cores)" -ForegroundColor Green
Write-Host "[OK]   - Host System RAM   : $RAM_GB GB" -ForegroundColor Green
Write-Host "[OK]   - GPU Vendor / Model: $GPU_Name" -ForegroundColor Green
Write-Host ""

# Verify & Auto-Install Python
Write-Host "[INFO] Verifying system prerequisites..." -ForegroundColor Blue
$PythonCmd = $null

function Test-PythonCandidate ($cmd) {
    try {
        $res = (& $cmd --version 2>&1).ToString()
        if ($res -like "Python 3*") { return $true }
    } catch {}
    return $false
}

if (Test-PythonCandidate "python") {
    $PythonCmd = "python"
} elseif (Test-PythonCandidate "py") {
    $PythonCmd = "py"
}

if (-not $PythonCmd) {
    Write-Host "[INFO] Python 3 not found on system. Installing Python 3.12 automatically via winget..." -ForegroundColor Yellow
    if (Get-Command "winget" -ErrorAction SilentlyContinue) {
        try {
            winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (Test-PythonCandidate "python") { $PythonCmd = "python" }
            elseif (Test-PythonCandidate "py") { $PythonCmd = "py" }
        } catch {
            Write-Host "[WARN] Automatic winget installation failed." -ForegroundColor Yellow
        }
    }
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python 3.10+ is required but could not be auto-installed." -ForegroundColor Red
    Write-Host "[ERROR] Please download & install Python 3.12 from https://www.python.org/downloads/ and check 'Add Python to PATH'." -ForegroundColor Red
    exit 1
}

$PyVersion = (& $PythonCmd --version 2>&1).ToString()
Write-Host "[OK] $PyVersion verified." -ForegroundColor Green

# Target Working Directory Resolution
#
# The Node package lives at "packages/node" since the 2026-08-04 monorepo migration.
# This script used to set $NodeDir to its own directory, find no pyproject.toml
# there (the repo root has none), fall through to the clone branch, and install
# Epichlo/Node-PublicIntelligence -- the ARCHIVED pre-monorepo repo. Windows hosts
# got no error; they got a node frozen before 1.4, 1.6, 2.1, 2.3 and 2.4. Silently
# installing stale software is worse than failing.
# See specs/installer-actually-installs.md.
$ScriptDir = Get-Location
if ($MyInvocation.MyCommand.Path -and (Test-Path -Path $MyInvocation.MyCommand.Path -PathType Leaf)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$RepoRoot = $ScriptDir
$NodeDir = Join-Path $RepoRoot "packages/node"

if (-not (Test-Path (Join-Path $NodeDir "pyproject.toml"))) {
    # Not run from inside a checkout: fetch the monorepo, then install the node
    # package from within it.
    $WorkDir = Join-Path $env:USERPROFILE "PublicIntelligence"
    if (Test-Path (Join-Path $WorkDir ".git")) {
        Write-Host "[INFO] Updating existing Public Intelligence checkout..." -ForegroundColor Blue
        git -C $WorkDir pull origin main --quiet
    } else {
        Write-Host "[INFO] Downloading Public Intelligence from GitHub..." -ForegroundColor Blue
        if (Test-Path $WorkDir) { Remove-Item -Path $WorkDir -Recurse -Force }
        if (Get-Command "git" -ErrorAction SilentlyContinue) {
            git clone --depth 1 https://github.com/Epichlo/Public-Intelligence.git $WorkDir --quiet
        } else {
            $ZipPath = Join-Path $env:TEMP "public_intelligence_main.zip"
            Invoke-WebRequest -Uri "https://github.com/Epichlo/Public-Intelligence/archive/refs/heads/main.zip" -OutFile $ZipPath
            Expand-Archive -Path $ZipPath -DestinationPath $env:TEMP -Force
            $Extracted = Join-Path $env:TEMP "Public-Intelligence-main"
            if (Test-Path $Extracted) {
                New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
                Copy-Item -Path "$Extracted\*" -Destination $WorkDir -Recurse -Force
                Remove-Item -Path $Extracted -Recurse -Force
            }
            if (Test-Path $ZipPath) { Remove-Item -Path $ZipPath -Force }
        }
    }
    $RepoRoot = $WorkDir
    $NodeDir = Join-Path $RepoRoot "packages/node"
}

if (-not (Test-Path (Join-Path $NodeDir "pyproject.toml"))) {
    Write-Host "[ERROR] Could not find the node package at $NodeDir." -ForegroundColor Red
    Write-Host "[ERROR] Expected 'packages/node/pyproject.toml' under $RepoRoot." -ForegroundColor Red
    exit 1
}

# Environment Setup
$EnvFile = Join-Path $NodeDir ".env"

# Empty by default: Zenoh then scouts the local network, which is correct for
# machines on one LAN and does not dial a host that does not exist.
$BootstrapRoutersJson = if ($BootstrapRouter.Count -gt 0) {
    "[" + (($BootstrapRouter | ForEach-Object { '"' + $_ + '"' }) -join ",") + "]"
} else {
    "[]"
}

# Per-install credential for the node's control API. The node binds 0.0.0.0, so
# without this any machine on the LAN could stop the node or spend its GPU. The
# API fails closed: no token means it serves nothing.
$AuthTokenBytes = New-Object 'System.Byte[]' 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($AuthTokenBytes)
$AuthToken = ($AuthTokenBytes | ForEach-Object { $_.ToString("x2") }) -join ''

if (-not (Test-Path $EnvFile)) {
    Write-Host "[INFO] Creating packages/node/.env configuration..." -ForegroundColor Blue
    $EnvContent = @"
NODE_ID=node-win-$($env:COMPUTERNAME.ToLower())
NODE_HOST=0.0.0.0
NODE_PORT=8080
NODE_SCHEDULER_URL=$SchedulerUrl
NODE_OLLAMA_HOST=http://localhost:11434
NODE_BOOTSTRAP_ROUTERS=$BootstrapRoutersJson
NODE_ZENOH_GOSSIP_SCOUTING=true
NODE_ZENOH_MULTICAST_SCOUTING=true
NODE_NETWORK_AUTH_TOKEN=$AuthToken
"@
    Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8
    Write-Host "[OK] Environment configured: $EnvFile" -ForegroundColor Green
    Write-Host "[OK] Generated NODE_NETWORK_AUTH_TOKEN for the local control API." -ForegroundColor Green
} else {
    (Get-Content $EnvFile) -replace "NODE_SCHEDULER_URL=.*", "NODE_SCHEDULER_URL=$SchedulerUrl" | Set-Content $EnvFile
    Write-Host "[OK] Updated NODE_SCHEDULER_URL in $EnvFile to $SchedulerUrl" -ForegroundColor Green

    # Upgrade path: installs predating the control-API credential have no token,
    # and the API fails closed, so add one rather than leave the node unreachable.
    if (-not (Select-String -Path $EnvFile -Pattern '^NODE_NETWORK_AUTH_TOKEN=' -Quiet)) {
        Add-Content -Path $EnvFile -Value "NODE_NETWORK_AUTH_TOKEN=$AuthToken"
        Write-Host "[OK] Added NODE_NETWORK_AUTH_TOKEN to $EnvFile (control API now requires it)." -ForegroundColor Green
    }
}

Write-Host "[INFO] Control API credential is in $EnvFile as NODE_NETWORK_AUTH_TOKEN." -ForegroundColor Blue
Write-Host "[INFO] Send it as the 'X-Network-Auth-Token' header, or set NODE_AUTH_TOKEN for the dashboard." -ForegroundColor Blue

# Virtual Environment
$VenvDir = Join-Path $NodeDir ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[INFO] Creating Python Virtual Environment in packages/node/.venv..." -ForegroundColor Blue
    & $PythonCmd -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
if (-not (Test-Path $VenvPythonw)) { $VenvPythonw = $VenvPython }
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host "[INFO] Installing Node dependencies..." -ForegroundColor Blue
& $VenvPip install -e "$NodeDir[dev]" --quiet

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "               Installation Complete! Host Node is Ready.                    " -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""

# Launch detached background daemon using native Windows pythonw.exe
Write-Host "Launching Host Node Daemon in persistent background..." -ForegroundColor Yellow
Start-Process -FilePath $VenvPythonw -ArgumentList "-m node.main --host 0.0.0.0 --port 8080" -WorkingDirectory $NodeDir -WindowStyle Hidden

Write-Host "[OK] Host Node daemon launched successfully in persistent background!" -ForegroundColor Green
Write-Host "[INFO] The node will continue running even if you close PowerShell." -ForegroundColor Blue
Write-Host ""
Write-Host "To manually check or restart your node, run:" -ForegroundColor Yellow
Write-Host "   & '$VenvPython' -m node.main --host 0.0.0.0 --port 8080" -ForegroundColor Cyan
