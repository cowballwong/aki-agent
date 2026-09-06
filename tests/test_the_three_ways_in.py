"""Three ways somebody arrives: a first install, an update, a merge.

All three existed. Two of them had drifted away from the code they describe,
and nothing could tell — a document is not executed, so a stale one keeps
being followed until somebody notices the result is wrong.



**The update path told the assistant to do it by hand.** Both INSTALL.md and
the `situation` report described `marketplace add` + `install` + `repair`,
which is three of the eight things `upgrade` does. The five left out are the
safety net: staging the new engine so a failure leaves the old one working,
keeping the previous version for `rollback`, closing the dashboard before
replacing the folder it runs from, the upgrade log, and naming the files the
person had edited before replacing them.

**The merge path never mentioned the screen.** Nine sections on capabilities
and not one line about a page — which is exactly what somebody who built their
own assistant would refuse to leave behind.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL = (REPO / "INSTALL.md").read_text(encoding="utf-8")
INTEGRATE = (REPO / "INTEGRATE.md").read_text(encoding="utf-8")


def test_all_three_ways_in_are_documented():
    assert "First install" in INSTALL
    assert "**Update**" in INSTALL
    assert "Merge into their own assistant" in INSTALL


def test_the_update_path_names_the_command_that_does_the_whole_job():
    """Not the three steps that are a subset of it."""
    assert "cli upgrade" in INSTALL, (
        "an update done by hand skips the parts nobody misses until they are "
        "needed")


def test_the_update_path_says_not_to_do_it_by_hand():
    """The old wording is still a plausible thing to try, so it is ruled out
    rather than merely replaced."""
    assert "Do NOT do this by hand" in INSTALL


def test_the_situation_report_names_the_upgrade_command_itself():
    """The machine says it, so the document cannot be the only thing that
    knows — that is how these two drifted apart in the first place."""
    from aki_agent import situation

    command = situation._upgrade_command(Path("C:/somewhere/aki-agent"))

    assert "aki_agent.cli upgrade" in command
    assert "--from" in command
    assert "--yes" in command


def test_the_merge_path_covers_the_screen_not_only_the_capabilities():
    """A page is what somebody who built their own assistant would miss."""
    assert "Bringing a PAGE across" in INTEGRATE
    assert "base.html" in INTEGRATE, (
        "the house style comes from extending one template, and that is the "
        "whole instruction")
    assert "dashboard/navigation.py" in INTEGRATE, (
        "a page the rail cannot reach is a page nobody opens")


def test_the_merge_path_warns_that_a_page_lives_in_the_engine():
    """Said at the time, not afterwards.

    An upgrade replaces the engine, so a page added this way goes back. Since
    0.31.0 it is named and copied aside first, which is not the same as being
    kept.
    """
    assert "an upgrade replaces the engine" in INTEGRATE.lower()


def test_the_merge_path_still_refuses_to_carry_somebody_else_s_data():
    """A template is the program; their client's name is not."""
    section = INTEGRATE[INTEGRATE.index("Bringing a PAGE across"):]
    assert "client names" in section


def test_the_import_path_says_a_screen_can_be_rebuilt():
    """"Your programs do not move" reads like "your screen is gone".

    It is not: the page can be built again in this package's style. Somebody
    deciding between the three routes should know that before choosing, not
    discover it afterwards.
    """
    choosing = (REPO / "CHOOSING.md").read_text(encoding="utf-8")

    assert "rebuilt" in choosing
    assert "6a" in choosing, "and it must say where the steps are"
