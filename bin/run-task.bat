@echo off
REM ------------------------------------------------------------
REM  Run one scheduled task.
REM
REM  This is the file Task Scheduler calls. It is not meant to be
REM  double-clicked, though running it with no arguments will list
REM  the tasks that exist.
REM
REM  Deliberately silent on success: a scheduled job that pops up a
REM  console window every hour gets switched off within a day.
REM ------------------------------------------------------------

chcp 65001 >nul 2>&1

REM Silent on failure, unlike the other two: Task Scheduler calls this
REM with no console attached, so there is nobody to read a message. The
REM exit code is what the scheduler records, and `doctor` now reports a
REM task that has been failing.
call "%~dp0_find_python.bat"
if not defined PYTHON_EXE exit /b 9009

%PYTHON_EXE% "%~dp0_bootstrap.py" aki_agent.tasks %*
