# Register a scheduled task: run run_telegram_ingest.ps1 every N minutes (default 2).
# Uses run_telegram_ingest_silent.vbs so no console flashes (WshShell.Run window style 0).
# Re-run this script after changing flags.
#
# Install:
#   .\scripts\register_telegram_ingest_schedule.ps1
#   .\scripts\register_telegram_ingest_schedule.ps1 -IntervalMinutes 3 -AlsoRun
# Remove:
#   .\scripts\register_telegram_ingest_schedule.ps1 -Unregister

param(
    [switch]$Unregister,
    [string]$TaskName = "job_finder-telegram-ingest",
    [int]$IntervalMinutes = 2,
    [switch]$AlsoRun
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run_telegram_ingest.ps1"
$vbsPath = Join-Path $PSScriptRoot "run_telegram_ingest_silent.vbs"
if (-not (Test-Path $scriptPath)) { Write-Error "Missing: $scriptPath" }
if (-not (Test-Path $vbsPath)) { Write-Error "Missing: $vbsPath" }

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task: $TaskName"
    } else {
        Write-Host "No scheduled task named: $TaskName"
    }
    exit 0
}

if ($IntervalMinutes -lt 1) {
    Write-Error "IntervalMinutes must be >= 1"
}

$arg = "//Nologo `"$vbsPath`""
if ($AlsoRun) {
    $arg += " -AlsoRun"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $arg
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Repeat every IntervalMinutes (anchor ~1 min from now so the task is valid today).
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Registered: $TaskName (every $IntervalMinutes min)"
Write-Host "  AlsoRun runner: $AlsoRun"
Write-Host "Test: Start-ScheduledTask -TaskName '$TaskName'"
