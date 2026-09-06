#!/bin/bash
# ---------------------------------------------------------------------
#  Health check launcher (macOS)
#
#  Double-click this file. It checks that everything the assistant needs
#  is present, and tells you in plain words what to do about anything
#  that is missing.
#
#  If macOS refuses to open it, right-click the file and choose Open --
#  that is Gatekeeper asking permission for a file downloaded from the
#  internet, and it only asks once.
#
#  This file is deliberately tiny. All the real logic lives in
#  bin/_bootstrap.py, so there is only ONE copy of it to keep correct
#  rather than one per platform.
# ---------------------------------------------------------------------

# Work from the folder this script is in, not wherever Finder started us.
cd "$(dirname "$0")" || exit 1

# macOS ships `python3`, never a bare `python`.
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo
  echo "  Python is not installed."
  echo
  echo "  The simplest way to get it:"
  echo "    1. Go to https://www.python.org/downloads/"
  echo "    2. Download the macOS installer and run it"
  echo "    3. Close this window and double-click this file again"
  echo
  read -r -p "  Press return to close. "
  exit 1
fi

"$PYTHON" ./_bootstrap.py aki_agent.doctor "$@"

echo
read -r -p "  Press return to close. "
