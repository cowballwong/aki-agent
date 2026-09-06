#!/bin/bash
# ------------------------------------------------------------
#  Run one scheduled task.
#
#  This is the file launchd calls. It is not meant to be
#  double-clicked, though running it with no arguments will list
#  the tasks that exist.
# ------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi

"$PYTHON" ./_bootstrap.py aki_agent.tasks "$@"
