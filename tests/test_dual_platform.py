"""Both platforms, or it is not finished.



He said it after a night in which every fix went into the .bat and none into
the .command. This file exists so the next one cannot: it asserts the SHAPE
of both halves rather than any one platform's behaviour, and it fails on a
Windows machine if the macOS half is missing.

WHAT THESE TESTS CANNOT DO. They fake the platform; they do not run on one.
Nobody here has a Mac, so the macOS branches are reasoned and covered, not
proven. That distinction belongs in the report every time, not only here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aki_agent import clones, launcher, paths, recycle


@pytest.fixture
def as_mac(monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: False)
    monkeypatch.setattr(paths, "is_macos", lambda: True)


@pytest.fixture
def as_windows(monkeypatch):
    monkeypatch.setattr(paths, "is_windows", lambda: True)
    monkeypatch.setattr(paths, "is_macos", lambda: False)


# ---------------------------------------------------------------------------
# The launcher ends the same way on both
# ---------------------------------------------------------------------------

def test_both_launchers_treat_a_replacement_as_a_replacement():
    """A recycled session exits non-zero on either platform, and on either it
    would otherwise be explained as a failure and then killed mid-explanation
    -- which is what keeps the dead window on screen."""
    note = str(recycle.deliberate_stop_file())

    windows = launcher.windows_launcher(launcher.LauncherOptions(), Path("."))
    mac = launcher.macos_launcher(launcher.LauncherOptions(), Path("."))

    assert f'if exist "{note}"' in windows
    assert f'if [ -f "{note}" ]' in mac


def test_both_launchers_still_explain_a_real_failure():
    """The thirty seconds exists because a launcher that vanishes on a broken
    install looks exactly like nothing having happened."""
    windows = launcher.windows_launcher(launcher.LauncherOptions(), Path("."))
    mac = launcher.macos_launcher(launcher.LauncherOptions(), Path("."))

    assert "This window closes in 30 seconds." in windows
    assert "This window closes in 30 seconds." in mac
    assert "timeout /t 30" in windows
    assert "sleep 30" in mac


def test_both_launchers_leave_cleanly():
    """A terminal keeps the window when its shell ends badly, on both."""
    windows = launcher.windows_launcher(launcher.LauncherOptions(), Path("."))
    mac = launcher.macos_launcher(launcher.LauncherOptions(), Path("."))

    assert windows.rstrip().endswith("exit /b 0")
    assert mac.rstrip().endswith("exit 0")


def test_the_note_is_read_before_the_wait_on_both():
    """Order is the whole fix. After the wait, the wait still happens."""
    windows = launcher.windows_launcher(launcher.LauncherOptions(), Path("."))
    mac = launcher.macos_launcher(launcher.LauncherOptions(), Path("."))

    assert windows.index("if exist") < windows.index('if not "%AKI_RC%"')
    assert mac.index("if [ -f") < mac.index('if [ "$AKI_RC" -ne 0 ]')


# ---------------------------------------------------------------------------
# A replacement gets a window on both
# ---------------------------------------------------------------------------

def test_a_mac_replacement_is_opened_in_terminal(as_mac, monkeypatch):
    """Running a .command directly gives a process with no terminal, which is
    the fault this function exists to prevent -- an assistant answering from
    somewhere nobody can look at."""
    asked: list[list[str]] = []

    def fake_run(command, **kwargs):
        asked.append(list(command))

        class Done:
            returncode = 0
            stdout = ""
        return Done()

    monkeypatch.setattr(recycle.subprocess if hasattr(recycle, "subprocess")
                        else __import__("subprocess"), "run", fake_run)
    # Nothing matching before, the session afterwards. Taking only what is
    # NEW is what stops a second assistant already running from being
    # mistaken for the replacement.
    answers = iter([[], [4242]])
    monkeypatch.setattr(recycle.session, "find_orphans",
                        lambda launcher_, exclude_pid=None: next(answers, [4242]))

    pid = recycle._start(["/Users/someone/Assistant/start.command"])

    assert asked and asked[0][:3] == ["open", "-a", "Terminal"]
    assert pid == 4242, "the pid has to be the session's, not `open`'s"


def test_a_mac_replacement_that_never_appears_is_reported_as_not_started(
        as_mac, monkeypatch):
    """`open` exits immediately whether or not anything came up. Returning its
    pid would have the caller EXCLUDE a process that is not the session, and
    then stop the real one -- so nothing appearing must be None."""
    monkeypatch.setattr(__import__("subprocess"), "run",
                        lambda *a, **k: type("D", (), {"returncode": 0,
                                                       "stdout": ""})())
    monkeypatch.setattr(recycle.session, "find_orphans",
                        lambda launcher_, exclude_pid=None: [])
    monkeypatch.setattr(recycle._time if hasattr(recycle, "_time")
                        else __import__("time"), "sleep", lambda _s: None)

    import time as real_time
    stamps = iter([0, 1, 999])
    monkeypatch.setattr(real_time, "time", lambda: next(stamps, 999))

    assert recycle._start(["/Users/someone/Assistant/start.command"]) is None


def test_a_clone_gets_a_window_on_a_mac_too(as_mac, monkeypatch):
    """The docstring promises one. On a Mac there was no code behind it."""
    seen: list[list[str]] = []

    monkeypatch.setattr(clones.runner, "find_claude", lambda: "/usr/bin/claude")

    def fake_run(command, **kwargs):
        seen.append(list(command))
        return type("D", (), {"returncode": 0, "stdout": "tab 1"})()

    monkeypatch.setattr(clones.subprocess, "run", fake_run)
    monkeypatch.setattr(clones, "_newest_session_pid", lambda *a: 77)

    pid = clones.launch("david-2", Path("/Users/someone/work"))

    assert pid == 77
    assert seen and seen[0][0] == "osascript"
    assert "Terminal" in seen[0][-1]


def test_a_windows_clone_still_gets_its_own_console(as_windows, monkeypatch):
    """The half that already worked has to keep working."""
    captured: dict = {}

    monkeypatch.setattr(clones.runner, "find_claude", lambda: "claude.exe")

    class FakePopen:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            self.pid = 5

    monkeypatch.setattr(clones.subprocess, "Popen", FakePopen)

    assert clones.launch("david-2", Path("C:/work")) == 5
    assert "creationflags" in captured
