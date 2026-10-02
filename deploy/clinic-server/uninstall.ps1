<#
.SYNOPSIS
  Removes the VociBot Enterprise clinic server. Clinical data is kept unless -DeleteData is given.
#>
param([switch]$DeleteData)
$ErrorActionPreference = "Stop"
foreach ($task in "VociBot Enterprise Server", "VociBot Ollama") {
  if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $task -Confirm:$false }
}
Get-NetFirewallRule -DisplayName "VociBot Enterprise Server" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Remove-Item -Recurse -Force (Join-Path $env:ProgramFiles "VociBot Enterprise Server") -ErrorAction SilentlyContinue
$dataDir = Join-Path $env:ProgramData "VociBot\clinic-server"
if ($DeleteData) {
  Remove-Item -Recurse -Force $dataDir
  Write-Host "Removed the server and ALL clinical data in $dataDir."
} else {
  Write-Host "Removed the server. Clinical data was kept in $dataDir (run with -DeleteData to remove it)."
}
