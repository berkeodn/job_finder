# Sync local jobs.db with the latest successful scrape artifact, preserving apply_status (same merge idea as apply.yml).
# Flow: (1) export apply statuses (2) download artifact (optional) (3) copy artifact over jobs.db (4) merge backup.
#
# After this + Telegram ingest (approved), your local step is done. Auto Apply Runner (schedule) does NOT apply here —
# it runs on the self-hosted runner: download artifact, merge, LinkedIn apply, upload artifact.
#
# Log (each run overwrites): logs/sync-then-ingest-latest.log — same idea as run_telegram_ingest.ps1 / telegram-ingest-latest.log.
#
# Usage (repo root):
#   .\scripts\sync_local_jobs_db_from_scrape_artifact.ps1
#   .\scripts\sync_local_jobs_db_from_scrape_artifact.ps1 -SkipDownload   # use existing .\jobs.db.scrape-artifact
#   .\scripts\sync_local_jobs_db_from_scrape_artifact.ps1 -RunTelegramIngest   # then run run_telegram_ingest.ps1
#   .\scripts\sync_local_jobs_db_from_scrape_artifact.ps1 -RunTelegramIngest -AlsoRun   # ingest + applicant runner

param(
    [switch]$SkipDownload,
    [string]$ArtifactFile = "",
    [switch]$RunTelegramIngest,
    [switch]$AlsoRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "sync-then-ingest-latest.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Convert-CapturedOutput {
    param($Objects)
    if ($null -eq $Objects) { return "" }
    @($Objects | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { "$_" }
        }) -join "`r`n"
}

function Write-SyncLog {
    param([System.Collections.Generic.List[string]]$Parts, [int]$ExitCode)
    $Parts.Add("===== exit code: $ExitCode =====")
    Set-Content -Path $LogFile -Value ($Parts -join "`r`n") -Encoding utf8
}

$VenvPy = Join-Path $RepoRoot "venv\Scripts\python.exe"
$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$parts = [System.Collections.Generic.List[string]]::new()
$parts.Add("===== $stamp sync_local_jobs_db_from_scrape_artifact SkipDownload=$SkipDownload RunTelegramIngest=$RunTelegramIngest AlsoRun=$AlsoRun =====")

if (-not (Test-Path $VenvPy)) {
    $parts.Add("ERROR: venv not found: $VenvPy")
    Write-SyncLog -Parts $parts -ExitCode 1
    exit 1
}

Set-Location $RepoRoot
$env:PYTHONIOENCODING = "utf-8"

$exitCode = 0

try {
    if (-not $SkipDownload) {
        $parts.Add("----- download_scrape_artifact_jobs_db -----")
        $dl = & (Join-Path $PSScriptRoot "download_scrape_artifact_jobs_db.ps1") 2>&1
        $parts.Add((Convert-CapturedOutput $dl))
        if ($LASTEXITCODE -ne 0) {
            $exitCode = $LASTEXITCODE
            throw "download_scrape_artifact_jobs_db.ps1 exit $LASTEXITCODE"
        }
    }

    $artifact = if ($ArtifactFile) { $ArtifactFile } else { Join-Path $RepoRoot "jobs.db.scrape-artifact" }
    if (-not (Test-Path $artifact)) {
        throw "Artifact DB not found: $artifact (run without -SkipDownload or set -ArtifactFile)"
    }

    $parts.Add("----- sync_local_jobs_db (python) -----")
    $py = & $VenvPy -m src.applicant.sync_local_jobs_db $artifact --repo-root $RepoRoot 2>&1
    $parts.Add((Convert-CapturedOutput $py))
    if ($LASTEXITCODE -ne 0) {
        $exitCode = $LASTEXITCODE
        throw "python sync_local_jobs_db exit $LASTEXITCODE"
    }

    if ($RunTelegramIngest) {
        $parts.Add("----- run_telegram_ingest (subprocess; see also logs/telegram-ingest-latest.log) -----")
        $ingest = Join-Path $PSScriptRoot "run_telegram_ingest.ps1"
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $ingest
        )
        if ($AlsoRun) {
            $argList += "-AlsoRun"
        }
        $ing = & powershell.exe @argList 2>&1
        $parts.Add((Convert-CapturedOutput $ing))
        if ($LASTEXITCODE -ne 0) {
            $exitCode = $LASTEXITCODE
            throw "run_telegram_ingest.ps1 exit $LASTEXITCODE"
        }
    }

    Write-SyncLog -Parts $parts -ExitCode $exitCode

    Write-Host ""
    if (-not $RunTelegramIngest) {
        Write-Host "Next (local):"
        Write-Host "  Run Telegram ingest: .\scripts\run_telegram_ingest.ps1  (or use -RunTelegramIngest next time)."
        Write-Host "  That finishes your part unless the self-hosted runner uses a different jobs.db (then copy this DB or run ingest there)."
    } else {
        Write-Host "Local sync + Telegram ingest step done."
    }
    Write-Host ""
    Write-Host "Apply + artifact upload: Auto Apply Runner (apply.yml) on the self-hosted machine (schedule)."
    Write-Host "Log: $LogFile"
} catch {
    $parts.Add("----- ERROR -----")
    $parts.Add(($_.Exception.Message))
    $parts.Add(($_ | Out-String))
    if ($exitCode -eq 0) { $exitCode = 1 }
    Write-SyncLog -Parts $parts -ExitCode $exitCode
    exit $exitCode
}

exit $exitCode
