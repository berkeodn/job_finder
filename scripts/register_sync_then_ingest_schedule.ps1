# Register scheduled task: download latest scrape jobs-db artifact -> merge into jobs.db -> Telegram ingest, every N minutes.
# Uses sync_then_ingest_silent.vbs (no console flash). Requires gh auth for download each run.
#
# Install:
#   .\scripts\register_sync_then_ingest_schedule.ps1
#   .\scripts\register_sync_then_ingest_schedule.ps1 -IntervalMinutes 5
#   .\scripts\register_sync_then_ingest_schedule.ps1 -AlsoRun
# Remove:
#   .\scripts\register_sync_then_ingest_schedule.ps1 -Unregister
# If legacy task job_finder-telegram-ingest exists: Unregister-ScheduledTask -TaskName 'job_finder-telegram-ingest' -Confirm:$false

param(
    [switch]$Unregister,
    [string]$TaskName = "job_finder-sync-then-telegram-ingest",
    [int]$IntervalMinutes = 2,
    [switch]$AlsoRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$vbsPath = Join-Path $PSScriptRoot "sync_then_ingest_silent.vbs"
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

if ($IntervalMinutes -lt 10) {
    Write-Warning "Artifact is downloaded from GitHub every $IntervalMinutes min; if you hit rate limits, increase -IntervalMinutes."
}

$arg = "//Nologo `"$vbsPath`""
if ($AlsoRun) {
    $arg += " -AlsoRun"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $arg -WorkingDirectory $RepoRoot
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
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
Write-Host "  Each run: gh download latest scrape jobs-db -> merge jobs.db -> RunTelegramIngest (AlsoRun: $AlsoRun)"
Write-Host "Test: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Requires: gh auth login. Legacy task removal: Unregister-ScheduledTask -TaskName 'job_finder-telegram-ingest' -Confirm:`$false"
