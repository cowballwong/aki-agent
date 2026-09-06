"""Nothing may float over the navigation — and scheduled tasks may read.

TWO FAILURES FROM THE SAME MORNING (reported 2026-08-21)
------------------------------------------------------
*"side bar 啲 button 唔 work, click 唔到"* and *"我讀唔到 house-rules.md
(權限未批)"*. Different halves of the package, the same shape: something was
built, and the thing it depended on was never wired to it.

**The nav.** The chat panel's drag handles are `position: fixed`, placed at
`right: calc(var(--chat-width) - 3px)`. That is correct only while the panel
is a fixed column. Below 980px the panel joins the normal flow and the handles
do not — so an invisible strip floats across the middle of the window, over
the navigation, and swallows the click on whichever item sits beneath it.
Nothing looks wrong. One button in the rail simply stops working, and which
one depends on the window width.

Found by asking the rendered page which element actually receives a click at
the centre of each rail link. "CHAT" answered `grip right`.

**The permissions.** Headless `claude -p` asks for permission like any other
session, and in a scheduled run nobody answers — so it is refused and the task
carries on regardless. The assistant's brief spends a whole section telling it
to read the house rules first; the scheduler ran it in a mode where it could
not. The task then reported, correctly and uselessly, that it had not followed
his standing instructions.

These are text-level checks. A real hit test needs a browser, which the suite
does not have — but both bugs are visible in the source if you know the shape,
and that is what these look for.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "src" / "aki_agent" / "dashboard" / "templates" / "base.html"
RUNNER = REPO_ROOT / "src" / "aki_agent" / "runner.py"


def _narrow_block() -> str:
    """The stylesheet's narrow-layout rules."""
    text = BASE.read_text(encoding="utf-8")
    start = text.index("@media (max-width: 980px)")
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise AssertionError("narrow media block never closed")


def test_the_drag_handles_are_hidden_when_the_panel_is_not_a_column():
    """The fix, held in place.

    The handles exist to resize a fixed side column. When there is no fixed
    side column they are a trap: still pinned, still on top, and invisible.
    """
    block = _narrow_block()
    assert re.search(r"\.grip\s*\{[^}]*display:\s*none", block), (
        "the drag handles are still live in the narrow layout, where they "
        "float over the navigation and eat a click")


def test_anything_pinned_to_the_chat_width_is_dealt_with_when_narrow():
    """The rule behind the fix, so the next such element cannot repeat it.

    Any element positioned from `--chat-width` is positioned relative to a
    column that only exists in the wide layout. Each one must be named in the
    narrow block — hidden, or repositioned — or it ends up somewhere arbitrary
    and on top of something.
    """
    text = BASE.read_text(encoding="utf-8")
    narrow = _narrow_block()

    pinned = set()
    for match in re.finditer(r"^(\.[A-Za-z0-9_.\- ]+)\s*\{([^}]*)\}", text, re.M):
        selector, body = match.group(1).strip(), match.group(2)
        if "var(--chat-width)" in body and "position: fixed" in text[
                max(0, match.start() - 200):match.end()]:
            pinned.add(selector.split()[0].split(":")[0])

    unhandled = [sel for sel in pinned
                 if sel not in narrow and sel.lstrip(".").split(".")[0]
                 not in narrow]
    assert not unhandled, (
        "these are pinned to the chat column's width but the narrow layout "
        f"never mentions them: {sorted(unhandled)}. In that layout the column "
        "is gone, so they land somewhere arbitrary — and if they sit above "
        "the navigation, they take its clicks.")


def test_a_scheduled_task_may_read_the_house_rules():
    """The brief tells it to read them. The scheduler must let it.

    Not a broad grant: read-only tools, plus the exact commands a task is
    told it may run. Anything that sends, posts or deletes still asks —
    which in a scheduled run means it declines, and that is the right way
    round.

    THIS TEST USED TO ASSERT THE BUG (rewritten 2026-08-23)
    -------------------------------------------------------
    It required `"Bash(python *)"` to be present, under a comment reading
    "The narrowing is the point". It was not a narrowing: `python -c "…"` is
    a general-purpose shell, so that grant was `Bash(*)` in a costume, and
    the test held it in place.

    A test that pins a specific string can only ever confirm that nobody
    changed it. What is actually wanted is a property — the run cannot get a
    shell it can put arbitrary code into — so that is what is checked now,
    against the real permission list rather than against the source text.
    """
    from aki_agent import runner

    source = RUNNER.read_text(encoding="utf-8")
    granted = runner.scheduled_tools()

    assert granted[0] == "--allowedTools", (
        "scheduled runs ask for permission with nobody there to answer")
    for tool in ("Read", "Grep", "Glob"):
        assert tool in granted, f"a scheduled task cannot {tool}"

    shells = [one for one in granted if one.startswith("Bash")]
    for one in shells:
        assert one != "Bash", "bare Bash was granted to headless runs"
        assert "*" not in one, (
            f"{one!r} is a wildcard shell grant. `python *` in particular is "
            "not a narrowing — `python -c` runs anything.")
        assert one.startswith('Bash(python "'), (
            f"{one!r} is not one of this package's own commands")

    # And nothing that reaches the outside world.
    for forbidden in ("WebFetch", "WebSearch", "--dangerously-skip-permissions"):
        assert forbidden not in source, (
            f"{forbidden} must not be granted to an unattended run")
        assert not any(forbidden in one for one in granted), (
            f"{forbidden} must not be granted to an unattended run")
