"""However you ask for the day to be written up, it is written in one place.


There are three ways to ask for the evening wrap-up now -- the dashboard's
End of day button, `aki_agent.cli eod` in a terminal, and saying "EOD" to the
assistant, which is the skill. Before this, only the first two existed and the
third quietly did something else: the live session improvised a summary of its
own. It read plausibly, it was not the scheduled job, it did not follow the
wrap-up's own instructions, and it was never saved as the day's record. Two
accounts of one day that do not match, and no way for the reader to tell which
one they are holding.

So all three go through `tasks.run_one("evening-wrapup")`. That function is
what writes the day log and what delivers the message, and these tests exist
to stop a fourth entrance being added beside it rather than through it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "src" / "aki_agent" / "dashboard" / "app.py"
CLI = ROOT / "src" / "aki_agent" / "cli.py"
SKILL = ROOT / "skills" / "end-of-day" / "SKILL.md"

THE_JOB = 'run_one("evening-wrapup")'


@pytest.fixture(scope="module")
def skill() -> str:
    assert SKILL.exists(), "the EOD skill is what makes 'EOD' on Telegram real"
    return SKILL.read_text(encoding="utf-8")


def test_the_dashboard_button_runs_the_scheduled_job():
    assert THE_JOB in DASHBOARD.read_text(encoding="utf-8")


def test_the_terminal_command_runs_the_same_job():
    assert THE_JOB in CLI.read_text(encoding="utf-8")


def test_the_command_exists_under_a_name_a_person_would_type():
    """`eod`, because that is the word he uses for it."""
    from aki_agent import cli

    assert cli.build_parser().parse_args(["eod"]).func is cli.cmd_eod


def test_the_skill_runs_the_command_rather_than_writing_its_own(skill):
    """The whole point of the skill.

    A model asked to "write up the day" will happily do it directly, and the
    result is the second account this file exists to prevent. So the skill
    has to name the command, and has to say not to.
    """
    assert "aki_agent.cli eod" in skill
    assert "Do not write the entry yourself" in skill


def test_the_skill_says_the_answer_is_already_on_its_way(skill):
    """Otherwise it lands twice.

    `run_one` delivers the entry through the user's channel itself. A session
    that also pastes it into its reply sends the same day twice, from two
    directions, in two slightly different shapes.
    """
    assert "already been sent" in skill


def test_the_skill_acknowledges_before_it_starts(skill):
    """One to two minutes of silence on a phone reads as a failed send.

    The dashboard has an overlay for this. The skill's equivalent is a line
    of text, and it has to come before the command rather than after it.
    """
    assert "before you start" in skill
    ack = skill.index("before you start")
    command = skill.index("aki_agent.cli eod")
    assert ack < command, (
        "the instruction to acknowledge must come before the command, or it "
        "is read after the model has already started waiting")


# ---------------------------------------------------------------------------
# The same rule, applied to the recycle
#
#
# It already was, and these pin it rather than change it. The working state
# has exactly one writer, `memory.write_working_state`, and all three
# entrances reach it: the twenty-minute schedule and the CLI verb both call
# `recycle.checkpoint()`, and the dashboard button's `recycle.perform()`
# writes the state itself as its first step, before anything can be lost.
# ---------------------------------------------------------------------------

def test_the_scheduled_checkpoint_and_the_typed_one_are_the_same_call():
    from aki_agent import cli, recycle

    assert cli.build_parser().parse_args(["checkpoint"]).func is cli.cmd_checkpoint
    assert "recycle.checkpoint()" in Path(cli.__file__).read_text(encoding="utf-8")
    assert callable(recycle.checkpoint)


def test_the_recycle_button_saves_to_the_same_file_before_restarting():
    """Step one of `perform`, and the reason the button can claim it.

    The overlay the button raises says "It saves where it is first, so
    nothing is lost." That sentence is only true while this line is.
    """
    source = (ROOT / "src" / "aki_agent" / "recycle.py").read_text(encoding="utf-8")

    assert "memory.write_working_state(state)" in source
    saves = source.index("memory.write_working_state(state)")
    restarts = source.index("def _start(")
    assert saves < restarts, "the state must be written before anything is killed"


# ---------------------------------------------------------------------------
# The handoff archive
# ---------------------------------------------------------------------------

def test_a_handoff_is_kept_under_its_own_name(tmp_path, monkeypatch):
    """The whole reason this exists.

    The live working-state file is one path and every write overwrites it,
    which is right -- a starting session needs the current handoff at a known
    place. It also meant that until 2026-09-04 the account of every previous
    handover was destroyed by the next one, so there was nothing to browse.
    """
    from aki_agent import memory, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    state = memory.WorkingState(generated_at=__import__("datetime").datetime.now(),
                                open_items=["a thing"], human_notes="mid-sentence")
    memory.record_handoff(state, kind=memory.HANDOFF_SYSTEM, why="session recycled")
    memory.record_handoff(state, kind=memory.HANDOFF_MANUAL, why="saved by hand")

    kept = memory.recent_handoffs()
    assert len(kept) == 2, "the second must not overwrite the first"
    assert {one.kind for one in kept} == {memory.HANDOFF_SYSTEM,
                                          memory.HANDOFF_MANUAL}
    # The notes are the half worth keeping: the lists above them can be
    # rebuilt from the workspace, what it was mid-doing cannot.
    assert "mid-sentence" in kept[0].body


def test_a_handoff_name_cannot_climb_out_of_the_folder(tmp_path, monkeypatch):
    """The name arrives in a query string."""
    from aki_agent import memory, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    memory.record_handoff(
        memory.WorkingState(generated_at=__import__("datetime").datetime.now()),
        kind=memory.HANDOFF_MANUAL, why="saved by hand")

    assert memory.read_handoff("../../config") is None
    assert memory.read_handoff("") is None


def test_the_detail_does_not_repeat_its_own_header(tmp_path, monkeypatch):
    """The page prints when, what kind and why in the heading already."""
    from aki_agent import memory, paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    memory.record_handoff(
        memory.WorkingState(generated_at=__import__("datetime").datetime.now()),
        kind=memory.HANDOFF_MANUAL, why="saved by hand")

    one = memory.recent_handoffs()[0]
    assert "kind: manual" in one.body
    assert "kind:" not in one.detail
    assert "why:" not in one.detail


def test_an_opened_handoff_can_be_closed_again():
    """An opened handoff can be closed again.

    Opening one added `h=` to the address and nothing ever took it off, so
    the panel stayed up until you left the tab. Two ways back out now: the
    row you opened toggles, and the panel has a close of its own.
    """
    text = (ROOT / "src" / "aki_agent" / "dashboard" / "templates"
            / "history.html").read_text(encoding="utf-8")

    assert "{% if not showing %}&amp;h={{ one.name }}{% endif %}" in text, (
        "the open row must link back WITHOUT h=, or it cannot be closed")
    assert 'class="closedetail"' in text
