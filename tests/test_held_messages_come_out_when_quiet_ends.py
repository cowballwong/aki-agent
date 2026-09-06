"""A quiet window that ends at three should not hold things until morning.

`release-held` ran once a day, at 08:05. Somebody who set quiet hours ending
at 15:00 got everything that had been held delivered the next morning, and
the page said so honestly after 2026-09-05 -- which made it a correctly
described wrong behaviour rather than a fixed one.
"""
from __future__ import annotations

import pytest

from aki_agent import schedule


def _release_task():
    for task in schedule.DEFAULT_TASKS:
        if task.key == "release-held":
            return task
    raise AssertionError("the release-held task is gone")


def test_it_no_longer_waits_for_a_single_time_of_day():
    """Asserts on `kind`, because `hour` is never None.

    `Trigger.hour` defaults to 9, so a test written as "no trigger has an
    hour" passes for every trigger ever made. The thing that decides whether
    this runs once a day is `kind`.
    """
    task = _release_task()
    daily = [t for t in task.triggers if t.kind == "time"]
    assert not daily, (
        f"release-held still has a once-a-day trigger at "
        f"{[(t.hour, t.minute) for t in daily]}, so a quiet window ending at "
        f"any other time holds until then")


def test_it_runs_often_enough_to_follow_a_window_closing():
    task = _release_task()
    intervals = [t.every_minutes for t in task.triggers
                 if t.kind == "interval" and t.every_minutes]
    assert intervals, "release-held has no interval trigger"
    assert min(intervals) <= 15, (
        f"every {min(intervals)} minutes is too long to feel like "
        f"'when quiet ends'")


def test_running_it_with_nothing_held_is_cheap(monkeypatch, tmp_path):
    """The reason ten minutes is affordable.

    If this ever started loading the configuration, or reaching a channel,
    before checking whether anything is waiting, the interval would become a
    hundred and forty pointless wake-ups a day.
    """
    from aki_agent import config as config_module, notify, paths, tasks

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    monkeypatch.setattr(notify, "held_count", lambda: 0)

    def must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "the configuration was loaded before checking whether anything "
            "was held")

    monkeypatch.setattr(config_module, "load", must_not_be_called)

    outcome = tasks.run_one("release-held")
    assert outcome.ok
    assert "nothing was held" in outcome.message
