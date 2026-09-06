@echo off
REM ---------------------------------------------------------------------
REM  Health check launcher (Windows)
REM
REM  Double-click this file. It checks that everything the assistant needs
REM  is present, and tells you in plain words what to do about anything
REM  that is missing.
REM
REM  This file is deliberately tiny. All the real logic lives in
REM  bin\_bootstrap.py, so there is only ONE copy of it to keep correct
REM  rather than one per platform.
REM ---------------------------------------------------------------------

setlocal

REM Show non-Latin characters properly. Without this a name or folder path
REM in another language prints as garbage or crashes the script.
chcp 65001 >nul 2>&1

call "%~dp0_find_python.bat"
if not defined PYTHON_EXE goto nopython

%PYTHON_EXE% "%~dp0_bootstrap.py" aki_agent.doctor %*
goto done

:nopython
echo.
echo   Python is not installed, or the one Windows found does not run.
echo.
echo   (Windows ships a placeholder called python.exe whose only job is
echo    to open the Microsoft Store. It is on PATH by default, so it can
echo    look installed when it is not.)
echo.
echo   1. Go to https://www.python.org/downloads/
echo   2. Download and run the installer
echo   3. IMPORTANT: tick "Add Python to PATH" on the first screen
echo   4. Close this window and double-click this file again
echo.

:done
echo.
pause
endlocal
