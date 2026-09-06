@echo off
REM ---------------------------------------------------------------------
REM  Set PYTHON_EXE to a Python that actually runs. Called by the other
REM  .bat files with `call "%~dp0_find_python.bat"`.
REM
REM  WHY THIS IS NOT `where python`
REM  ------------------------------
REM  Windows 10 and 11 ship a zero-byte stub at
REM  %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe whose only job is to
REM  open the Microsoft Store. It is on PATH by default, so `where python`
REM  finds it and reports success on a machine with no Python at all --
REM  and then `python whatever.py` opens the Store instead of running the
REM  script, with no error and no output.
REM
REM  The check that works is to run it. A Python that cannot print its own
REM  version is not a Python we can use, whatever PATH says about it.
REM
REM  `py` is tried too, and second. The launcher is installed by the
REM  python.org installer even when "Add to PATH" was not ticked -- which
REM  is the box people miss -- so it is often the only working route on a
REM  machine where Python genuinely is installed.
REM ---------------------------------------------------------------------

set "PYTHON_EXE="

python -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  goto :eof
)

py -3 -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py -3"
  goto :eof
)

goto :eof
