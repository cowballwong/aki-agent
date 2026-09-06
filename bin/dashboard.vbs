' Open the dashboard with no window at all.
'
' WHY (reported 2026-08-19)
' -----------------------
' "i don't want to see any terminal showing up... the ONLY terminal show
' should be the Claude Code session."
'
' The launcher used `start "" /min`, which still puts a console on the
' taskbar and steals focus for a moment. A .bat run by Windows always gets a
' console; the only way to have none is to start it from a script host that
' can ask for a hidden window, which is what this does -- the same trick as
' run-task.vbs, for the same reason.
'
' It does NOT wait: the dashboard is a long-running server, and waiting here
' would hold the launcher open for as long as the dashboard lives.

Option Explicit

Dim shell, folder, command

Set shell = CreateObject("WScript.Shell")
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
command = """" & folder & "dashboard.bat"""

' 0 = no window. False = do not wait.
shell.Run command, 0, False
