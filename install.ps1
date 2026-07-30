# ==============================================================================
# Public Intelligence - One-Click Windows Host Node Installer (PowerShell)
# ==============================================================================
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

# Verify Python
Write-Host "[INFO] Verifying system prerequisites..." -ForegroundColor Blue
$PythonCmd = $null
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PythonCmd = "py"
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python 3.10+ is required but not found in PATH." -ForegroundColor Red
    Write-Host "[ERROR] Please install Python 3.10+ from https://www.python.org/downloads/ and check 'Add Python to PATH'." -ForegroundColor Red
    exit 1
}

$PyVersion = & $PythonCmd --version
Write-Host "[OK] $PyVersion verified." -ForegroundColor Green

# Environment Setup
$ScriptDir = Get-Location
if ($MyInvocation.MyCommand.Path -and (Test-Path -Path $MyInvocation.MyCommand.Path -PathType Leaf)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$NodeDir = Join-Path $ScriptDir "Node"
if (-not (Test-Path $NodeDir)) {
    $NodeDir = $ScriptDir
}

$EnvFile = Join-Path $NodeDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[INFO] Creating Node/.env configuration..." -ForegroundColor Blue
    $EnvContent = @"
NODE_ID=node-win-$($env:COMPUTERNAME.ToLower())
NODE_HOST=0.0.0.0
NODE_PORT=8080
NODE_SCHEDULER_URL=http://localhost:8000
NODE_OLLAMA_HOST=http://localhost:11434
NODE_BOOTSTRAP_ROUTERS=["tcp/bootstrap.public-intelligence.net:7447"]
NODE_ZENOH_GOSSIP_SCOUTING=true
NODE_ZENOH_MULTICAST_SCOUTING=true
TELEMETRY_SECRET_KEY=pi_telemetry_secure_default_secret_key
"@
    Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8
    Write-Host "[OK] Environment configured: $EnvFile" -ForegroundColor Green
}

# Virtual Environment
$VenvDir = Join-Path $NodeDir ".venv"
if (-not (Test-Path $VenvDir)) {
    Write-Host "[INFO] Creating Python Virtual Environment in Node/.venv..." -ForegroundColor Blue
    & $PythonCmd -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

Write-Host "[INFO] Installing Node dependencies..." -ForegroundColor Blue
& $VenvPip install -e "$NodeDir[dev]" --quiet

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "               Installation Complete! Host Node is Ready.                    " -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start your Host Node daemon on Windows, run:" -ForegroundColor Yellow
Write-Host "   & '$VenvPython' -m node.main --host 0.0.0.0 --port 8080" -ForegroundColor Cyan
