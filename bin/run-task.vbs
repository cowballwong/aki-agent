' Run one scheduled task with no window at all.
'
' WHY THIS FILE EXISTS (reported 2026-08-19)
' ----------------------------------------
' Task Scheduler runs a task as the logged-in user, and a .bat run that way
' always gets a console window -- so every twenty minutes a black box flashed
' up over whatever he was doing. run-task.bat's own header already said that
' "a scheduled job that pops up a console window every hour gets switched off
' within a day"; it was right, and the .bat could not honour it by itself.
'
' Windows has no schtasks flag for this. The <Hidden> element in a task's XML
' hides the task from the Task Scheduler list, not the window it opens. The
' working answer on Windows is to start the batch file from a script host that
' can ask for a hidden window, which is what this does.
'
' It waits for the batch file rather than returning immediately, so that Task
' Scheduler sees the real duration and its "do not start a new instance while
' one is running" rule still means something.

Option Explicit

Dim shell, arguments, folder, command, i

Set shell = CreateObject("WScript.Shell")
Set arguments = WScript.Arguments

folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
command = """" & folder & "run-task.bat"""

For i = 0 To arguments.Count - 1
    command = command & " """ & arguments(i) & """"
Next

' 0 = no window. True = wait for it to finish.
WScript.Quit shell.Run(command, 0, True)
