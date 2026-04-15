# Download the latest successful "Job Finder Pipeline" (scrape.yml) jobs-db artifact to a local SQLite file.
# Requires: GitHub CLI — https://cli.github.com/ — and: gh auth login
#
# Usage (from repo root):
#   .\scripts\download_scrape_artifact_jobs_db.ps1
#   .\venv\Scripts\python.exe -m src.applicant.inspect_jobs_db --db .\jobs.db.scrape-artifact
#
# Manual alternative: GitHub → Actions → Job Finder Pipeline → latest green run → Artifacts → jobs-db → unzip jobs.db

param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputPath) {
    $OutputPath = Join-Path $RepoRoot "jobs.db.scrape-artifact"
}

# Scheduled tasks often get a minimal PATH; gh may not resolve even if it works in an interactive shell.
function Get-GhExe {
    $cmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "${env:ProgramFiles}\GitHub CLI\gh.exe",
        "${env:LocalAppData}\Programs\GitHub CLI\gh.exe",
        "${env:ProgramFiles(x86)}\GitHub CLI\gh.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

$gh = Get-GhExe
if (-not $gh) {
    Write-Error "GitHub CLI (gh) not found. Install from https://cli.github.com/ then run: gh auth login"
}

Set-Location $RepoRoot

$runsJson = & $gh run list --workflow "Job Finder Pipeline" --status success --limit 1 --json databaseId,url 2>$null
if (-not $runsJson) {
    Write-Error "gh run list failed. Run from a cloned repo with GitHub remote, or check gh auth."
}

$runs = $runsJson | ConvertFrom-Json
if (-not $runs -or $runs.Count -eq 0) {
    Write-Error "No successful 'Job Finder Pipeline' run found."
}

$runId = $runs[0].databaseId
$runUrl = $runs[0].url
# Write-Output so parent scripts (e.g. sync -> logs) can capture this stream; Write-Host is not captured.
Write-Output "Using run $runId"
Write-Output $runUrl

$tmp = Join-Path $env:TEMP "jobs-db-artifact-$runId"
if (Test-Path $tmp) {
    Remove-Item -Recurse -Force $tmp
}
New-Item -ItemType Directory -Path $tmp | Out-Null

& $gh run download $runId -n jobs-db -D $tmp

$db = Get-ChildItem -Path $tmp -Filter "jobs.db" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $db) {
    Write-Error "jobs.db not found inside downloaded artifact (under $tmp)."
}

Copy-Item $db.FullName -Destination $OutputPath -Force
Remove-Item -Recurse -Force $tmp

Write-Output ""
Write-Output "Saved: $OutputPath"
Write-Output "Inspect: .\venv\Scripts\python.exe -m src.applicant.inspect_jobs_db --db `"$OutputPath`""
