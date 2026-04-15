' Run sync_local_jobs_db_from_scrape_artifact.ps1 hidden (window style 0).
' Each run: download latest scrape jobs-db from GitHub -> merge into jobs.db -> Telegram ingest (-RunTelegramIngest).
' Optional WScript args: -AlsoRun -> forwarded to PowerShell
Option Explicit
Dim sh, fso, scriptDir, ps1, cmd, i, code
Set sh = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = scriptDir & "\sync_local_jobs_db_from_scrape_artifact.ps1"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """ -RunTelegramIngest"
For i = 0 To WScript.Arguments.Count - 1
    cmd = cmd & " " & WScript.Arguments(i)
Next
code = sh.Run(cmd, 0, True)
WScript.Quit code
