' Run run_telegram_ingest.ps1 with no visible window (window style 0).
' Optional args forwarded to PowerShell, e.g. -AlsoRun
Option Explicit
Dim sh, fso, scriptDir, ps1, cmd, i, code
Set sh = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = scriptDir & "\run_telegram_ingest.ps1"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
For i = 0 To WScript.Arguments.Count - 1
    cmd = cmd & " " & WScript.Arguments(i)
Next
' 0 = hidden; True = wait — propagate exit code
code = sh.Run(cmd, 0, True)
WScript.Quit code
