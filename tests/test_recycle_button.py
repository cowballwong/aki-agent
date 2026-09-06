"""What the recycle button did on a real machine, 2026-09-03 evening.

It reported "Restarted and confirmed" while the session the owner was looking
at was untouched, and the replacement it started had no window -- so the
assistant answered messages from a place nobody could see. The owner found it
before any of these tests existed. They exist so it stays found.
"""

from __future__ import annotations

import os

import pytest

from aki_agent import paths, recycle, session


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    yield


# ---------------------------------------------------------------------------
# Saying what really happened
# ---------------------------------------------------------------------------

def test_it_does_not_call_it_a_restart_when_it_stopped_nothing():
    """The old wording was true about the half it measured -- something new
    is running -- and wrong about the half that matters."""
    report = recycle.RecycleReport(attempted=True, completed=True,
                                   reason="started after the instruction",
                                   stopped=0)

    said = report.summary()

    assert "Restarted and confirmed" not in said
    assert "Nothing was stopped" in said
    assert "two" in said


def test_a_real_restart_still_reads_like_one():
    report = recycle.RecycleReport(attempted=True, completed=True,
                                   reason="from the expected launcher",
                                   stopped=1)

    assert report.summary().startswith("Restarted and confirmed")
    assert "Stopped 1" in report.summary()


# ---------------------------------------------------------------------------
# Finding the session there is no marker for
# ---------------------------------------------------------------------------

def test_the_old_session_is_looked_for_even_with_no_marker(monkeypatch):
    """Only a previous recycle writes a marker. A session started by
    double-clicking the launcher has none -- which described every first
    recycle on every machine."""
    assert session.read_marker() is None

    asked: list[str] = []
    monkeypatch.setattr(session, "find_orphans",
                        lambda launcher, **kw: asked.append(launcher) or [])
    monkeypatch.setattr(recycle, "_start", lambda command: 4321)
    monkeypatch.setattr(recycle, "should_recycle",
                        lambda *a, **k: session.RestartAdvice(
                            safe=True, reason="idle", idle_seconds=10_000))
    monkeypatch.setattr(session, "verify_restart",
                        lambda *a, **k: session.Verification(True, "started"))

    recycle.perform([r"C:\somewhere\start-assistant.bat"],
                    holds_connection=False, confirmed=True, settle_seconds=0)

    assert asked == [r"C:\somewhere\start-assistant.bat"]


def test_the_marker_still_wins_when_there_is_one(monkeypatch):
    """It names the launcher the running session was actually started with,
    which beats the one we were handed."""
    session.record_launch(999, launcher="the-old-launcher.bat")

    asked: list[str] = []
    monkeypatch.setattr(session, "find_orphans",
                        lambda launcher, **kw: asked.append(launcher) or [])
    monkeypatch.setattr(recycle, "_start", lambda command: 4321)
    monkeypatch.setattr(recycle, "should_recycle",
                        lambda *a, **k: session.RestartAdvice(
                            safe=True, reason="idle", idle_seconds=10_000))
    monkeypatch.setattr(session, "verify_restart",
                        lambda *a, **k: session.Verification(True, "started"))

    recycle.perform(["a-different-launcher.bat"], holds_connection=False,
                    confirmed=True, settle_seconds=0)

    assert asked == ["the-old-launcher.bat"]


# ---------------------------------------------------------------------------
# Somewhere the owner can see it
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="the window flags are Windows'")
def test_the_replacement_gets_a_window_of_its_own(monkeypatch):
    """The dashboard has no window. A child inherits that, and the owner
    reported the result as 'a hidden session' -- one he could talk to and
    never see."""
    import subprocess

    seen: dict = {}

    class Fake:
        pid = 77

    def fake_popen(command, **kwargs):
        seen.update(kwargs)
        return Fake()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("WT_SESSION", "inherited-from-the-dashboard")

    assert recycle._start(["start-assistant.bat"]) == 77

    assert seen["creationflags"] & subprocess.CREATE_NEW_CONSOLE
    # The launcher reads both of these before deciding whether to open a
    # terminal. Leaving either as the dashboard had it is what hid it.
    assert seen["env"]["AKI_NO_WT"] == "1"
    assert "WT_SESSION" not in seen["env"]


# ---------------------------------------------------------------------------
# The order, changed on the owner's instruction 2026-09-03:
# "Recycle 要開新 session, 通咗 telegram 再 kill 舊 session"
# ---------------------------------------------------------------------------

def _happy_path(monkeypatch, order):
    """Wire up a recycle whose every real effect is recorded, not performed."""
    monkeypatch.setattr(recycle, "should_recycle",
                        lambda *a, **k: session.RestartAdvice(
                            safe=True, reason="idle", idle_seconds=10_000))
    monkeypatch.setattr(recycle, "_start",
                        lambda command: order.append("started") or 4321)
    monkeypatch.setattr(recycle, "_terminate",
                        lambda pid: order.append(f"stopped {pid}") or [pid])
    monkeypatch.setattr(session, "find_orphans", lambda launcher, **kw: [111])
    monkeypatch.setattr(session, "verify_restart",
                        lambda *a, **k: session.Verification(True, "started"))
    monkeypatch.setattr(recycle, "_wait_for_channel",
                        lambda before, **kw: order.append("channel up")
                        or (True, "the messaging connection came up"))


def test_it_starts_the_new_one_before_it_stops_the_old(monkeypatch):
    """Stopping first leaves a gap with no assistant at all, and if the
    replacement then fails to start there is nothing left running."""
    order: list[str] = []
    _happy_path(monkeypatch, order)

    recycle.perform(["start-assistant.bat"], holds_connection=True,
                    confirmed=True, settle_seconds=0)

    assert order.index("started") < order.index("stopped 111")


def test_it_waits_for_the_connection_before_stopping_the_old(monkeypatch):
    order: list[str] = []
    _happy_path(monkeypatch, order)

    recycle.perform(["start-assistant.bat"], holds_connection=True,
                    confirmed=True, settle_seconds=0)

    assert order.index("channel up") < order.index("stopped 111")


def test_a_replacement_that_will_not_start_leaves_the_old_one_alone(monkeypatch):
    """The whole reason for starting first."""
    order: list[str] = []
    _happy_path(monkeypatch, order)
    monkeypatch.setattr(recycle, "_start", lambda command: None)

    report = recycle.perform(["start-assistant.bat"], holds_connection=True,
                             confirmed=True, settle_seconds=0)

    assert not report.completed
    assert "left running" in report.reason
    assert not [step for step in order if step.startswith("stopped")]


def test_it_never_stops_the_session_it_just_started(monkeypatch):
    """`find_orphans` matches on the launcher path, and the replacement was
    started with the very same launcher."""
    order: list[str] = []
    _happy_path(monkeypatch, order)
    monkeypatch.setattr(session, "find_orphans",
                        lambda launcher, exclude_pid=None: [
                            pid for pid in (111, 4321) if pid != exclude_pid])

    recycle.perform(["start-assistant.bat"], holds_connection=True,
                    confirmed=True, settle_seconds=0)

    assert "stopped 4321" not in order
    assert "stopped 111" in order


def test_the_button_may_force_past_a_refusal(monkeypatch):
    """reported 2026-09-03: after the confirm dialog it should just do it."""
    order: list[str] = []
    _happy_path(monkeypatch, order)
    monkeypatch.setattr(recycle, "should_recycle",
                        lambda *a, **k: session.RestartAdvice(
                            safe=False, reason="busy", idle_seconds=1))

    refused = recycle.perform(["start-assistant.bat"], holds_connection=False,
                              confirmed=True, settle_seconds=0)
    assert not refused.attempted

    forced = recycle.perform(["start-assistant.bat"], holds_connection=False,
                             confirmed=True, force=True, settle_seconds=0)
    assert forced.attempted
    assert forced.forced
    assert "Forced" in forced.summary()


def test_the_scheduled_recycle_cannot_force(monkeypatch):
    """Nobody asked for the automatic one, so it must never interrupt."""
    import inspect

    body = inspect.getsource(recycle.checkpoint)
    assert "force" not in body


def test_stopping_the_wrapper_stops_the_session_it_started(monkeypatch):
    """`cmd /c start-assistant.bat` is what carries the launcher path, so it
    is what gets found -- but claude.exe is its child, and killing only the
    wrapper is how a session ends up running with no parent and no window."""
    stopped: list[int] = []

    class FakeProcess:
        def __init__(self, pid, kids=()):
            self.pid = pid
            self._kids = list(kids)

        def children(self, recursive=False):
            return self._kids

        def terminate(self):
            stopped.append(self.pid)

        def kill(self):
            stopped.append(self.pid)

    child = FakeProcess(222)
    wrapper = FakeProcess(111, [child])

    class FakePsutil:
        @staticmethod
        def Process(pid):
            return wrapper

        @staticmethod
        def wait_procs(procs, timeout=None):
            return procs, []

    monkeypatch.setattr(session, "_psutil", lambda: FakePsutil)

    # Both are reported stopped -- the session is gone either way.
    assert sorted(recycle._terminate(111)) == [111, 222]
    # Only the child is KILLED. The wrapper is left to reach its own
    # `exit /b 0`, because a terminal keeps a dead pane on screen when the
    # process it hosts is killed and closes it when the process finishes.
    # Killing both is what left the owner an old window that looked alive
    # beside the new session (2026-09-04).
    assert stopped == [222]


def test_a_wrapper_that_will_not_leave_is_killed_anyway(monkeypatch):
    """A tidy window never outranks actually stopping the session.

    An older launcher with no tidy exit, or one sitting on `pause`, does not
    end when its child does. It still has to go -- a session left holding the
    bot token is the failure the whole recycle exists to prevent."""
    stopped: list[int] = []

    class FakeProcess:
        def __init__(self, pid, kids=()):
            self.pid = pid
            self._kids = list(kids)

        def children(self, recursive=False):
            return self._kids

        def terminate(self):
            stopped.append(self.pid)

        def kill(self):
            stopped.append(self.pid)

    child = FakeProcess(222)
    wrapper = FakeProcess(111, [child])

    class FakePsutil:
        @staticmethod
        def Process(pid):
            return wrapper

        @staticmethod
        def wait_procs(procs, timeout=None):
            # Nothing ever leaves on its own.
            return [], list(procs)

    monkeypatch.setattr(session, "_psutil", lambda: FakePsutil)

    assert sorted(recycle._terminate(111)) == [111, 222]
    # The child is terminated then killed; the wrapper, having refused to go,
    # is terminated and killed too.
    assert 111 in stopped and 222 in stopped


def test_the_dashboard_is_not_taken_down_with_the_session(monkeypatch):
    """It is a child of the same launcher, and it is the page the owner is
    standing on. The replacement cannot put it back either: its launcher
    tries to start one before the old session dies, and finds the port
    taken."""
    stopped: list[int] = []

    class FakeProcess:
        def __init__(self, pid, command, kids=()):
            self.pid = pid
            self._command = command
            self._kids = list(kids)

        def cmdline(self):
            return self._command

        def children(self, recursive=False):
            return self._kids

        def terminate(self):
            stopped.append(self.pid)

        def kill(self):
            stopped.append(self.pid)

    the_session = FakeProcess(222, ["claude.exe", "--channels", "plugin:x"])
    the_dashboard = FakeProcess(333, ["wscript.exe", "dashboard.vbs"])
    wrapper = FakeProcess(111, ["cmd", "/c", "start-assistant.bat"],
                          [the_session, the_dashboard])

    class FakePsutil:
        @staticmethod
        def Process(pid):
            return wrapper

        @staticmethod
        def wait_procs(procs, timeout=None):
            return procs, []

    monkeypatch.setattr(session, "_psutil", lambda: FakePsutil)

    recycle._terminate(111)

    assert 222 in stopped, "the session itself must go"
    assert 111 not in stopped, (
        "the launcher wrapper is left to exit on its own, so its terminal "
        "pane closes instead of staying on screen looking alive")
    assert 333 not in stopped, "but not the dashboard"


# ---------------------------------------------------------------------------
# A replaced session is not a failed one
# ---------------------------------------------------------------------------

def test_a_deliberate_stop_leaves_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()

    recycle.say_this_was_deliberate()

    assert recycle.deliberate_stop_file().exists()


def test_the_note_is_taken_back_if_nothing_was_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    paths.ensure_app_dirs()
    recycle.say_this_was_deliberate()

    recycle.forget_the_deliberate_stop()

    assert not recycle.deliberate_stop_file().exists()


def test_leaving_the_note_never_raises(tmp_path, monkeypatch):
    """A tidy window is not worth failing a restart for."""
    monkeypatch.setattr(paths, "state_dir",
                        lambda: tmp_path / "nowhere" / "deeper")
    monkeypatch.setattr(paths, "ensure_app_dirs",
                        lambda: (_ for _ in ()).throw(OSError("read only")))

    recycle.say_this_was_deliberate()   # must not raise


def test_the_launcher_reads_that_note_before_explaining_anything(tmp_path,
                                                                 monkeypatch):
    """The defect this whole pair exists for (reported 2026-09-04).

    A recycled session exits non-zero, so the launcher explained the
    "failure" and waited thirty seconds; `_terminate` gives it eight and then
    kills it; a killed process is what makes Windows Terminal keep the pane.

    Order is the assertion. The note has to be read BEFORE the branch that
    waits, or the wait still happens and the window still stays.
    """
    from pathlib import Path

    from aki_agent import launcher

    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    script = launcher.windows_launcher(launcher.LauncherOptions(), Path("."))

    note = str(recycle.deliberate_stop_file())
    assert f'if exist "{note}"' in script

    assert script.index("if exist") < script.index('if not "%AKI_RC%"'), (
        "the wait would still happen")
    assert script.rstrip().endswith("exit /b 0")
