"""Two switches that reported success and did nothing.

Both were invisible to the existing suite for the same reason: the tests
supplied the thing that was broken. The channel tests pass `channel="file"`
explicitly, so they never exercised the default the scheduler actually uses;
the schedule tests install a task and assert it is installed, which was true
and not the question.

Found by the Fable 5.1 audit pass, 2026-09-05.
"""

from __future__ import annotations

import pytest

from aki_agent import schedule, tasks


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    from aki_agent import paths

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Switching an Event example on


def an_example():
    """One of the three shipped Events, which all ship switched off."""
    for task in schedule.DEFAULT_TASKS:
        if not task.enabled:
            return task
    pytest.skip("no shipped task is disabled any more")


def test_the_shipped_events_still_ship_switched_off():
    """Guards the premise. If they ship on, the rest tests nothing."""
    off = [one for one in schedule.DEFAULT_TASKS if not one.enabled]
    assert off, "nothing ships disabled -- has the default changed?"


def test_switching_a_shipped_example_on_makes_it_actually_run():
    """It used to register with the OS and stay disabled.

    `run_one` then returned `ok=True, "switched off, nothing to do"` every
    ten minutes, so the row read "on" and the task recorded a clean run each
    time while doing nothing whatsoever.
    """
    example = an_example()

    schedule.set_enabled(example.key, True)

    again = schedule.get_task(example.key)
    assert again.enabled is True
    outcome = tasks.run_one(example.key, channel="file")
    assert outcome.message != "switched off, nothing to do"


def test_switching_it_off_restores_the_shipped_default_not_a_stored_no():
    """`forget`, not `set(False)`.

    A user task taken out of the scheduler must still run when somebody
    presses Run now. Storing "off" for both cases would have got that wrong
    silently -- the same shape as the bug being fixed.
    """
    example = an_example()

    schedule.set_enabled(example.key, True)
    schedule.forget_enabled(example.key)

    assert example.key not in schedule.enabled_overrides()
    assert schedule.get_task(example.key).enabled is False


def test_an_override_survives_a_release_changing_the_default():
    """Only differences are stored, which is why the store exists."""
    schedule.set_enabled("morning-summary", False)

    assert schedule.get_task("morning-summary").enabled is False
    # And every reader agrees, because it is applied in `all_tasks`.
    listed = {one.key: one.enabled for one in schedule.all_tasks()}
    assert listed["morning-summary"] is False


# ---------------------------------------------------------------------------
# Where a task says what it has to say


def test_a_task_with_no_channel_goes_where_the_user_reads(monkeypatch):
    """The scheduler calls `run_one` with `channel=""`.

    The two sentinel branches -- release-held and the Me-time watcher -- read
    `channel or "file"` and returned before the line that answers this
    question, so both delivered to `logs/messages.md` on a machine with
    Telegram connected. Delivered to a file IS delivered, so nothing
    complained: the queue was cleared and the digest was never read.
    """
    from aki_agent import channels

    monkeypatch.setattr(channels, "best", lambda config=None: "telegram")

    assert tasks._where_to_say("morning-summary", None) == "telegram"


def test_a_task_the_user_silenced_still_goes_to_the_file(monkeypatch):
    """Switched off means stop interrupting, not stop running."""
    from aki_agent import channels

    monkeypatch.setattr(channels, "best", lambda config=None: "telegram")
    schedule.set_announce("morning-summary", False)

    assert tasks._where_to_say("morning-summary", None) == "file"


def test_an_explicit_channel_always_wins(monkeypatch):
    """What the CLI and every existing test pass."""
    from aki_agent import channels

    monkeypatch.setattr(channels, "best", lambda config=None: "telegram")

    assert tasks._where_to_say("morning-summary", None, "file") == "file"


def test_the_two_sentinels_ask_the_same_question_as_everything_else():
    """Stated against the source, because the bug WAS the duplication.

    Four lines of channel-picking existed once, in the wrong place. Any
    reappearance of `channel or "file"` is that bug coming back.
    """
    from pathlib import Path

    source = Path(tasks.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]        # past the module docstring
    assert 'channel or "file"' not in body.replace(
        '`channel or "file"`', "")           # the one mention is a comment
