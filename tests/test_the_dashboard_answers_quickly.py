"""Pages must answer a button press, not think about it.

reported 2026-08-23: "optimize dashboard reaction time, 有幾個 button 我按落去
都要等好耐."

Measured before fixing rather than guessed at, because the cause was not
where it looked. `/schedule` took 9.42 seconds, and none of it was rendering:
the template kwargs called `installed_names()` once per task inside a
comprehension, and every call shells out to `schtasks /Query`, which walks
every job on the machine — 1.32 seconds on a machine with 403 of them.
"""
import time

import pytest

from aki_agent import schedule


def test_asking_the_scheduler_twice_only_asks_once(monkeypatch):
    """The N+1 that cost nine seconds."""
    asked = []

    def counted():
        asked.append(1)
        return ["AkiAgent-morning-summary"]

    monkeypatch.setattr(schedule, "_ask_the_scheduler", counted)
    schedule.forget_what_is_installed()

    for _ in range(10):
        schedule.installed_names()

    assert len(asked) == 1, (
        f"the scheduler was asked {len(asked)} times for one answer")


def test_acting_on_the_schedule_forgets_what_was_cached(monkeypatch):
    """Looking straight after acting must not show the previous answer.

    This is the one moment where a stale cache genuinely misleads, so it is
    invalidated explicitly rather than left to expire.
    """
    monkeypatch.setattr(schedule, "_ask_the_scheduler",
                        lambda: ["AkiAgent-morning-summary"])
    schedule.forget_what_is_installed()
    schedule.installed_names()
    assert schedule._ASKED is not None

    # install() and remove() both clear it, whichever way they return.
    monkeypatch.setattr(schedule, "_install",
                        lambda *a, **k: (False, "nope"))
    schedule.install(schedule.DEFAULT_TASKS[0], schedule.runner_script(),
                     confirmed=True)
    assert schedule._ASKED is None, "a failed install left the cache in place"


def test_a_refusal_is_never_cached(monkeypatch):
    """A machine that could not be asked has to be asked again.

    Caching the failure would turn a momentary lock into a lasting one.
    """
    def refuses():
        raise schedule.CouldNotAsk("denied")

    monkeypatch.setattr(schedule, "_ask_the_scheduler", refuses)
    schedule.forget_what_is_installed()
    with pytest.raises(schedule.CouldNotAsk):
        schedule.installed_names()
    assert schedule._ASKED is None


def test_the_schedule_page_asks_the_scheduler_once(monkeypatch):
    """The page that took 9.4 seconds.

    Counted rather than timed: a timing assertion on a shared machine is a
    flaky test, and the count is what actually went wrong.
    """
    asked = []

    def counted():
        asked.append(1)
        return []

    monkeypatch.setattr(schedule, "_ask_the_scheduler", counted)
    schedule.forget_what_is_installed()

    from aki_agent.dashboard import create_app

    with create_app().test_client() as browser:
        assert browser.get("/schedule").status_code == 200
    assert len(asked) <= 1, (
        f"one page render asked the scheduler {len(asked)} times; each one "
        "shells out to schtasks over every job on the machine")
