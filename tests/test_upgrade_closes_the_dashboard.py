"""The upgrade closes the dashboard first, and says so.

WHY (reported 2026-08-21)
-----------------------

The dashboard runs out of the engine folder, and an upgrade renames that
folder underneath it. What survives is a process serving code that is no
longer on disk: it answers normally, it reports the new version number, and
it hands back the previous build's pages. On 2026-08-20 that cost a whole
round trip — the upgrade said 0.20.0 and his browser showed the old rail, and
neither of us could see which was lying.

Both halves of his instruction are tested here: closed **first**, and the
person **told**. A dashboard that disappears without a word reads as a crash.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = REPO_ROOT / "src" / "aki_agent" / "engine.py"
CLI = REPO_ROOT / "src" / "aki_agent" / "cli.py"


def _upgrade_source() -> str:
    text = CLI.read_text(encoding="utf-8")
    start = text.index("def cmd_upgrade(")
    end = text.index("\ndef ", start + 10)
    return text[start:end]


def test_the_dashboard_is_closed_before_the_engine_is_replaced():
    """Order is the whole point. Closing it afterwards fixes nothing."""
    body = _upgrade_source()
    closing = body.index("stop_dashboard")
    swapping = body.index("engine.copy_engine")
    assert closing < swapping, (
        "the dashboard is closed after the swap, which is too late — the "
        "process has already lost the folder it was running from")


def test_the_person_is_told_it_was_closed():
    """His instruction was 要提 user, and it is half the requirement.

    Something that shuts a window somebody was using, silently, teaches them
    not to trust the thing that did it.
    """
    body = _upgrade_source()
    assert "Closing your dashboard" in body, "it closes without saying so"
    assert "was closed for this upgrade" in body, (
        "the end of the run never mentions that the dashboard is shut, so it "
        "looks like it crashed during the upgrade")


def test_being_unable_to_check_is_not_reported_as_nothing_running():
    """The third state again.

    Process inspection needs psutil, which is optional. Without it the honest
    answer is "cannot tell" — and the upgrade says so, rather than carrying on
    as though the dashboard were closed and letting the stale-pages confusion
    happen anyway.
    """
    body = _upgrade_source()
    assert "can_see_processes" in body
    assert "cannot check for an open dashboard" in body


def test_the_search_never_counts_itself():
    """The bug this rule exists for, on 2026-08-20.

    The first version of this check matched processes by command line — and
    its own command line contained the marker it was searching for. It found
    itself, reported one dashboard more than existed, and I told the maintainer he had
    a duplicate to clean up. He did not.
    """
    source = ENGINE.read_text(encoding="utf-8")
    start = source.index("def dashboard_processes(")
    body = source[start:source.index("\ndef ", start + 10)]

    assert "os.getpid()" in body, (
        "a command-line search that does not exclude its own process is "
        "reading its own reflection")
    assert re.search(r'if process\.info\["pid"\] == mine:\s*\n\s*continue',
                     body), "the current process is not actually skipped"


def test_a_missing_psutil_reports_nothing_rather_than_crashing():
    """Optional means optional. The upgrade must still run without it."""
    source = ENGINE.read_text(encoding="utf-8")
    start = source.index("def dashboard_processes(")
    body = source[start:source.index("\ndef ", start + 10)]
    assert "except Exception" in body and "return []" in body


def test_it_never_tells_him_how_many_dashboards_are_open():
    """Because it does not know, and the number it has means something else.

    `dashboard_processes()` counts processes, and one dashboard is a chain of
    them — the launcher's python, the bootstrap, the server. One running
    dashboard on the test machine reported as six. Printing that would tell him
    he had six windows open.

    It is the same shape as the duplicate-session count on 2026-08-20: a
    number that is exactly what was measured and not at all what it appears to
    say. The count belongs in the log, where it is labelled as processes.
    """
    body = _upgrade_source()
    assert "len(open_dashboards)} window" not in body, (
        "the process count is being shown to the user as a window count")
    assert "Closing your dashboard." in body

    # It is still recorded, but labelled honestly.
    assert "process(es)" in body
