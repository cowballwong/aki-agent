"""Serve Today with one item of each kind in it, for looking at.

Not a test. Tests assert; this exists so the queue panel can be driven in a
real browser, which is where the last four layout faults were found and is
the only place `position: fixed`, scrollbars and animation directions are
actually true.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "src"))

home = Path(tempfile.mkdtemp(prefix="aki-demo-")) / "01_Config"
home.mkdir(parents=True)
os.environ["AKI_AGENT_HOME"] = str(home)

from aki_agent import approvals  # noqa: E402
from aki_agent.dashboard import create_app  # noqa: E402

approvals.ask(
    "Hollow Lane — party wall award still not returned",
    body="Sent 12 Aug. Chased once. The award has to be in before the "
         "contractor can break ground on the flank wall.",
    kind="waiting", waiting_on="Winchester council",
    due="2026-08-19", project="P-2418",
)
approvals.ask(
    "Barnet loft — which staircase option goes in the drawing?",
    body="Option A keeps the existing landing and loses 300mm of head "
         "height at the top. Option B moves the landing and needs the "
         "bathroom wall taken out.",
    kind="question", due="2026-08-25", project="P-2431",
)
approvals.ask(
    "Reply to Thomas about the deck",
    body="Draft: thanks for the notes, both versions are attached, the "
         "photo pages keep the full images so you can recrop them.",
    kind="draft", project="P-2440",
)
approvals.ask(
    "Radlett garage — client has not confirmed the brick",
    body="Two samples sent on 6 Aug.",
    kind="waiting", waiting_on="Mr Whittaker", due="2026-08-30",
    project="P-2427",
)

app = create_app(HERE / "configs" / "examples" / "architecture.yaml")
app.config["TESTING"] = True
print(f"demo home: {home}", flush=True)
app.run(host="127.0.0.1", port=5199, debug=False, use_reloader=False)
