<#
.SYNOPSIS
  Installs VociBot Enterprise - clinic server (vocibotenterpriseclinicserver) on this Windows PC.
.DESCRIPTION
  Run from an elevated PowerShell in the unzipped package folder:
      powershell -ExecutionPolicy Bypass -File .\install.ps1 [-Port 8443] [-HardwareProfile windows-16gb]
  - Copies the server to "C:\Program Files\VociBot Enterprise Server".
  - Creates C:\ProgramData\VociBot\clinic-server (database, recordings, models,
    certificates) readable only by Administrators and SYSTEM.
  - Runs the server at startup without anyone signing in (restarts on failure),
    and Ollama too when it is installed.
  - Opens the port in Windows Firewall on Private and Domain networks only.
#>
param(
  [int]$Port = 8443,
  [ValidateSet("windows-16gb", "windows-8gb")][string]$HardwareProfile = "windows-16gb",
  [switch]$SkipProvision
)
$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this script from an elevated PowerShell (Run as administrator)."
}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$programDir = Join-Path $env:ProgramFiles "VociBot Enterprise Server"
$dataDir = Join-Path $env:ProgramData "VociBot\clinic-server"
$exe = Join-Path $programDir "vocibot-server.exe"

Write-Host "Installing program files to $programDir"
Get-ScheduledTask -TaskName "VociBot Enterprise Server" -ErrorAction SilentlyContinue | Stop-ScheduledTask -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $programDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $here "vocibot-server\*") $programDir

Write-Host "Preparing protected data folder $dataDir"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
# Clinical data: Administrators and SYSTEM only (no inherited access for Users).
icacls $dataDir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
$profileFile = Join-Path $dataDir "vocibot.env"
if (-not (Test-Path $profileFile)) { Copy-Item (Join-Path $here "profiles\$HardwareProfile.env") $profileFile }

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

$ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
if (-not $ollama) {
  $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path $candidate) { $ollama = Get-Item $candidate }
}
if ($ollama) {
  Write-Host "Running Ollama as a background service for the note model"
  # One shared note model, one request at a time: memory stays fixed.
  $modelDir = Join-Path $env:ProgramData "VociBot\ollama-models"
  New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
  foreach ($pair in @(@("OLLAMA_MODELS", $modelDir), @("OLLAMA_NUM_PARALLEL", "1"), @("OLLAMA_MAX_LOADED_MODELS", "1"))) {
    [Environment]::SetEnvironmentVariable($pair[0], $pair[1], "Machine")
  }
  # The desktop Ollama app would compete for the port and keep models elsewhere.
  Get-Process "ollama app", "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  $ollamaPath = if ($ollama.Source) { $ollama.Source } else { $ollama.FullName }
  $ollamaAction = New-ScheduledTaskAction -Execute $ollamaPath -Argument "serve"
  Register-ScheduledTask -TaskName "VociBot Ollama" -Action $ollamaAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName "VociBot Ollama"
  Start-Sleep -Seconds 5
} else {
  Write-Warning "Ollama was not found. Install it from https://ollama.com, then run this script again so notes can be written."
}

if (-not $SkipProvision) {
  Write-Host "Downloading speech models and the note model (needs internet)..."
  & $exe provision --edition clinic-server --data-dir $dataDir
  if ($LASTEXITCODE -ne 0) { Write-Warning "Provisioning did not finish; run it again later: `"$exe`" provision --edition clinic-server --data-dir `"$dataDir`"" }
}

Write-Host "Registering the VociBot background service (scheduled task at startup)"
$action = New-ScheduledTaskAction -Execute $exe -Argument "serve --edition clinic-server --data-dir `"$dataDir`" --port $Port" -WorkingDirectory $programDir
Register-ScheduledTask -TaskName "VociBot Enterprise Server" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Opening port $Port in Windows Firewall (Private and Domain networks only)"
Get-NetFirewallRule -DisplayName "VociBot Enterprise Server" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "VociBot Enterprise Server" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private,Domain | Out-Null

Start-ScheduledTask -TaskName "VociBot Enterprise Server"
Start-Sleep -Seconds 8
$hostName = [System.Net.Dns]::GetHostName()
Write-Host ""
Write-Host "VociBot Enterprise clinic server is running."
Write-Host "  Address for doctors:   https://$($hostName):$Port"
Write-Host "  Certificate to trust:  https://$($hostName):$Port/ca.crt  (also $dataDir\certs\vocibot-ca.crt)"
Write-Host "  First visit creates the administrator account."
Write-Host "  See README-clinic-server.md for installing the certificate on each device."
