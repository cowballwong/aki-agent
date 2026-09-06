@echo off
REM ------------------------------------------------------------
REM  Open the dashboard.
REM
REM  Double-click this. It starts the dashboard and opens your
REM  browser. It only listens on this computer -- nothing outside
REM  can reach it.
REM ------------------------------------------------------------

chcp 65001 >nul 2>&1

call "%~dp0_find_python.bat"
if not defined PYTHON_EXE (
  echo.
  echo   Python is not installed, or the one Windows found does not run.
  echo   Get it from https://www.python.org/downloads/ and tick
  echo   "Add Python to PATH" on the first screen.
  echo.
  pause
  exit /b 1
)

%PYTHON_EXE% "%~dp0_bootstrap.py" aki_agent.dashboard.app %*
