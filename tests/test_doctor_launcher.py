"""The check that would have caught a silently incomplete macOS install.

Somebody finished setup, started their assistant, and got a Claude Code
session with no dashboard. Two causes, and every check then in `doctor` passed
both: the launcher had never been written, and `bin/dashboard.command` had
arrived without its executable bit. Neither is something a person can report,
because from where they sit nothing happened.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aki_agent import doctor


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An assistant folder of our own, so the real one is never read."""
    monkeypatch.setenv("AKI_AGENT_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)
    return tmp_path / "home"


def test_a_missing_launcher_is_a_failure_with_the_command_to_fix_it(
        home, monkeypatch):
    """The whole of the first cause. Before this, nothing had an opinion about
    a launcher that was not there -- `check_engine` reads one only if it
    exists, and `_repoint` rewrites one on the same condition."""
    monkeypatch.setattr(doctor, "_run", lambda module, rest: f"{module} {rest}")
    check = doctor.check_launcher()

    assert check.ok is False
    assert check.warning_only is False
    assert "make-launcher --dashboard --yes" in check.fix


def test_a_launcher_that_cannot_run_is_a_failure_on_macos(
        home, monkeypatch):
    """The second cause. On macOS a script at 0o644 fails in a Finder dialog
    that names no reason; started in the background by another script, it
    fails with no dialog at all."""
    from aki_agent import launcher, paths

    monkeypatch.setattr(paths, "is_windows", lambda: False)
    monkeypatch.setattr(doctor, "_run", lambda module, rest: f"{module} {rest}")
    target = paths.app_dir() / "start-assistant.command"
    target.write_text("#!/bin/bash" + chr(10), encoding="utf-8")
    monkeypatch.setattr(launcher, "launcher_path", lambda name="x": target)
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    check = doctor.check_launcher()

    assert check.ok is False
    assert "start-assistant.command" in check.detail
    assert "repair --yes" in check.fix


def test_a_launcher_without_the_dashboard_still_passes_but_says_so(
        home, monkeypatch):
    """Somebody may have said no to the dashboard, and that is their choice.
    It is worth one clause of detail, not a failure."""
    from aki_agent import launcher, paths

    monkeypatch.setattr(paths, "is_windows", lambda: True)
    target = paths.app_dir() / "start-assistant.bat"
    target.write_text("claude --agent assistant" + chr(10), encoding="utf-8")
    monkeypatch.setattr(launcher, "launcher_path", lambda name="x": target)

    check = doctor.check_launcher()

    assert check.ok is True
    assert "does not open the dashboard" in check.detail


def test_it_is_one_of_the_checks_that_actually_runs():
    """A check nothing calls is a check that reports nothing -- which is the
    shape of the bug it was written for."""
    import inspect

    source = inspect.getsource(doctor.run_all)
    assert "check_launcher()" in source
