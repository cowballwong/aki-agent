"""Not re-registering a launchd job that has not changed.

macOS posts a "Background Items Added" notification every time a LaunchAgent
is loaded. `_repoint` reinstalls every enabled task, and both `repair` and
`upgrade` call it — so one update threw one notification per task at the
user, repeatedly, for jobs already registered with the identical definition.
The report came with a screenshot of seven stacked notifications naming the
same file.

The notification cannot be suppressed and should not be: it is macOS telling
somebody that software has arranged to run itself. What was wrong was doing
the thing that triggers it for no reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import paths, schedule


@pytest.fixture()
def on_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: False)
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(schedule, "running_elevated", lambda: False)
    (tmp_path / "Library" / "LaunchAgents").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def runner(tmp_path):
    """A runner that exists. `install` refuses one that does not, which is
    what stops a task being created and then failing silently for ever."""
    script = tmp_path / "run-task.command"
    script.write_text("#!/bin/bash", encoding="utf-8")
    return script


def a_task():
    return schedule.all_tasks()[0]


def test_an_unchanged_job_is_not_re_registered(on_macos, runner, monkeypatch):
    """The whole point. Nothing is written, nothing is loaded, and macOS has
    no reason to say anything."""
    task = a_task()
    schedule.launchd_plist_path(task).write_text(
        schedule.launchd_plist(task, runner), encoding="utf-8")
    monkeypatch.setattr(schedule, "_launchd_is_loaded", lambda label: True)

    called = []
    monkeypatch.setattr(schedule.subprocess, "run",
                        lambda *a, **k: called.append(a) or None)

    ok, message = schedule.install(task, runner, confirmed=True)

    assert ok is True
    assert "already scheduled" in message
    assert called == []


def test_a_changed_job_is_re_registered(on_macos, runner, monkeypatch):
    """The skip must be about the definition, not about the file existing.
    A job whose command changed and was left alone is a task pointing at a
    folder that is about to be deleted."""
    task = a_task()
    schedule.launchd_plist_path(task).write_text(
        "something else entirely", encoding="utf-8")
    monkeypatch.setattr(schedule, "_launchd_is_loaded", lambda label: True)

    ran = []

    class Done:
        returncode = 0
        stdout = stderr = ""

    def fake_run(command, **kw):
        ran.append(command[:2])
        return Done()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)

    ok, _ = schedule.install(task, runner, confirmed=True)

    assert ok is True
    assert ["launchctl", "unload"] in ran
    assert ["launchctl", "load"] in ran


def test_a_job_launchd_has_forgotten_is_re_registered(
        on_macos, runner, monkeypatch):
    """A plist on disk that launchd is not holding is not a scheduled task.
    Skipping on the file alone would leave somebody with a task they believe
    is running and is not -- which is worse than a notification."""
    task = a_task()
    schedule.launchd_plist_path(task).write_text(
        schedule.launchd_plist(task, runner), encoding="utf-8")
    monkeypatch.setattr(schedule, "_launchd_is_loaded", lambda label: False)

    ran = []

    class Done:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(schedule.subprocess, "run",
                        lambda command, **kw: ran.append(command[:2]) or Done())

    ok, _ = schedule.install(task, runner, confirmed=True)

    assert ok is True
    assert ["launchctl", "load"] in ran


def test_launchctl_that_cannot_be_asked_means_carry_on(monkeypatch):
    """False is the safe answer. A wrong False costs one redundant
    notification; a wrong True loses somebody's scheduled work silently."""
    def explode(*a, **k):
        raise OSError("launchctl is not here")

    monkeypatch.setattr(schedule.subprocess, "run", explode)
    assert schedule._launchd_is_loaded("com.aki-agent.x") is False
