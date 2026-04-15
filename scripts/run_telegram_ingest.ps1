# Poll Telegram (getUpdates) and write apply:* callbacks -> jobs.db as approved.
# Requires no bot webhook (Telegram getWebhookInfo url empty) so getUpdates receives updates.
#
# Schedule (sync + ingest): .\scripts\register_sync_then_ingest_schedule.ps1
# Log: logs/telegram-ingest-latest.log (overwritten each run — only last run kept).
#
# Examples:
#   .\scripts\run_telegram_ingest.ps1
#   .\scripts\run_telegram_ingest.ps1 -AlsoRun   # ingest then applicant runner
#   .\scripts\run_telegram_ingest.ps1 -VerboseLog   # full Python stdout every run (larger logs)

param(
    [switch]$AlsoRun,
    # If set, always append full ingest/runner output. Default: one-line "idle" when nothing to do.
    [switch]$VerboseLog
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPy = Join-Path $RepoRoot "venv\Scripts\python.exe"
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "telegram-ingest-latest.log"

if (-not (Test-Path $VenvPy)) {
    Write-Error "venv not found: $VenvPy"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:PYTHONIOENCODING = "utf-8"
Set-Location $RepoRoot

function Invoke-VenvPythonCapturing {
    param([string]$Python, [string[]]$Arguments, [string]$WorkDir)
    Push-Location $WorkDir
    try {
        $lines = @(& $Python @Arguments 2>&1)
        $exit = $LASTEXITCODE
        if ($null -eq $exit) { $exit = 0 }
        $text = ($lines | ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { "$_" }
            }) -join "`r`n"
        return @{ Text = $text; ExitCode = $exit }
    } finally {
        Pop-Location
    }
}

$stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

$code = 0
try {
    $r1 = Invoke-VenvPythonCapturing -Python $VenvPy -Arguments @("-m", "src.applicant.telegram_ingest") -WorkDir $RepoRoot
    $code = $r1.ExitCode

    $r2 = $null
    if ($AlsoRun -and $code -eq 0) {
        $r2 = Invoke-VenvPythonCapturing -Python $VenvPy -Arguments @("-m", "src.applicant.runner") -WorkDir $RepoRoot
        $code = $r2.ExitCode
    }

    # Parse "Telegram ingest finished: N callback(s) -> DB" so non-zero runs always get full log, not one-line idle.
    $ingestCount = $null
    if ($r1.Text -match 'Telegram ingest finished:\s*(\d+)\s*callback') {
        $ingestCount = [int]$Matches[1]
    }
    $ingestIdle = ($r1.ExitCode -eq 0) -and ($ingestCount -eq 0)
    # If telegram_poll logged anything (queue ack, duplicate apply, etc.), keep full stdout in the log file.
    # Otherwise idle mode would only write one line and drop those INFO lines.
    $hasTelegramPollDetail = $r1.Text -match 'telegram_poll: Ingest:'
    $runnerIdle = $false
    if ($AlsoRun -and $null -ne $r2) {
        $runnerIdle = ($r2.ExitCode -eq 0) -and ($r2.Text -match "No pending applications")
    }
    $useOneLine = (-not $VerboseLog) -and $ingestIdle -and ((-not $AlsoRun) -or $runnerIdle) -and (-not $hasTelegramPollDetail)

    if ($useOneLine) {
        $line = "[$stamp] idle ingest=0 callbacks"
        if ($AlsoRun) { $line += " runner=no pending" }
        $line += " exit=$code"
        Set-Content -Path $LogFile -Value $line -Encoding utf8
        Write-Output $line
    } else {
        $parts = [System.Collections.Generic.List[string]]::new()
        $parts.Add("===== $stamp run_telegram_ingest AlsoRun=$AlsoRun =====")
        if (($null -ne $ingestCount) -and ($ingestCount -gt 0)) {
            $parts.Add("[ingest] $ingestCount callback(s) processed - full output below")
        }
        if ($r1.Text) {
            $parts.Add($r1.Text)
            Write-Output $r1.Text
        }
        if ($AlsoRun -and $null -ne $r2) {
            $parts.Add("----- runner -----")
            if ($r2.Text) {
                $parts.Add($r2.Text)
                Write-Output $r2.Text
            }
        }
        $parts.Add("===== exit code: $code =====")
        Set-Content -Path $LogFile -Value ($parts -join "`r`n") -Encoding utf8
    }
} catch {
    Set-Content -Path $LogFile -Value ("[$stamp] ERROR: " + ($_ | Out-String)) -Encoding utf8
    throw
}

exit $code
