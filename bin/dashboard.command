#!/bin/bash
# ------------------------------------------------------------
#  Open the dashboard.
#
#  Double-click this. It starts the dashboard and opens your
#  browser. It only listens on this computer -- nothing outside
#  can reach it.
#
#  If macOS refuses to open it, right-click and choose Open.
# ------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi

"$PYTHON" ./_bootstrap.py aki_agent.dashboard.app "$@"
