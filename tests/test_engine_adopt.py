"""The environment handed to a process that must be the NEW engine.

A program that replaces itself has one recurring trap: the process doing the
replacing is the version being replaced. `upgrade` works around it with a
subprocess; these tests are about that subprocess actually getting there.
"""

from __future__ import annotations

from pathlib import Path

from aki_agent import engine


# ---------------------------------------------------------------------------
# The environment a new process needs to be the NEW engine
# ---------------------------------------------------------------------------

def test_a_stale_package_on_pythonpath_is_dropped(tmp_path, monkeypatch):
    """The defect this exists for (reported 2026-09-04).

    `upgrade` hands the re-pointing to a fresh process so the NEW code does
    it. The bootstrap had exported the OLD package's `src` on `PYTHONPATH`,
    the child inherited it, and an explicit `PYTHONPATH` beats an editable
    install -- so the fresh process ran 0.41.3 and rewrote his launcher
    without the `TELEGRAM_STATE_DIR` line 0.41.4 added.
    """
    old = tmp_path / "old-release" / "src"
    (old / "aki_agent").mkdir(parents=True)
    target = tmp_path / "engine"
    (target / "src" / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(old))

    assert "PYTHONPATH" not in engine.env_for(target)


def test_the_engine_being_run_stays_on_the_path(tmp_path, monkeypatch):
    target = tmp_path / "engine"
    mine = target / "src"
    (mine / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(mine))

    assert engine.env_for(target)["PYTHONPATH"] == str(mine)


def test_someone_elses_pythonpath_is_left_alone(tmp_path, monkeypatch):
    """It only removes what shadows this package. Anything else is theirs."""
    theirs = tmp_path / "their-own-library"
    theirs.mkdir()
    target = tmp_path / "engine"
    (target / "src" / "aki_agent").mkdir(parents=True)

    monkeypatch.setenv("PYTHONPATH", str(theirs))

    assert engine.env_for(target)["PYTHONPATH"] == str(theirs)


def test_no_pythonpath_at_all_is_not_invented(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert "PYTHONPATH" not in engine.env_for(tmp_path)


# ---------------------------------------------------------------------------
# What an install is made of
# ---------------------------------------------------------------------------

def test_the_manifest_is_a_file_that_exists_in_this_checkout():
    """Every entry has to be real, or an install is missing part of itself."""
    from pathlib import Path

    root = Path(engine.__file__).resolve().parents[2]
    missing = [one for one in engine.COPIED if not (root / one).exists()]
    assert not missing, missing


# ---------------------------------------------------------------------------
# The executable bit on the scripts a user double-clicks
# ---------------------------------------------------------------------------

def test_a_command_file_that_lost_its_executable_bit_gets_it_back(
        tmp_path, monkeypatch):
    """A real macOS install, seen with `ls -l`.

    `bin/dashboard.command` was `-rw-r--r--`. The launcher starts that file in
    the background, so the permission denial went to a job nobody reads:
    Claude Code opened normally and the dashboard simply never appeared, with
    nothing anywhere saying why. `copy2` had faithfully carried a 0o644 off
    the source.

    ASSERTED ON THE CALL, NOT ON THE RESULTING MODE
    -----------------------------------------------
    Windows ignores the executable bit, so a `stat()` here reads back 0o666
    whatever was asked for, and the first version of this test failed on the
    machine it was written on while testing nothing. What is being checked is
    that the code asks -- which is the whole of its job; granting is the
    filesystem's.
    """
    monkeypatch.setattr(engine.os, "name", "posix")
    root = tmp_path / "engine" / "bin"
    root.mkdir(parents=True)
    script = root / "dashboard.command"
    script.write_text("#!/bin/bash" + chr(10), encoding="utf-8")
    script.chmod(0o644)

    asked = []
    real = Path.chmod
    monkeypatch.setattr(
        Path, "chmod",
        lambda self, mode, **kw: (asked.append((self.name, mode)),
                                  real(self, mode, **kw))[1])

    assert engine.make_runnable(tmp_path / "engine") == 1
    assert len(asked) == 1
    name, mode = asked[0]
    assert name == "dashboard.command"
    assert mode & 0o111 == 0o111


def test_files_that_are_not_scripts_are_left_alone(tmp_path, monkeypatch):
    """Only `.sh` and `.command`. Marking a whole tree executable to fix two
    files would be a wider change than the problem, and on a synced drive it
    is the kind of change that shows up as noise in every later diff."""
    monkeypatch.setattr(engine.os, "name", "posix")
    root = tmp_path / "engine"
    root.mkdir()
    (root / "config.json").write_text("{}", encoding="utf-8")

    asked = []
    monkeypatch.setattr(Path, "chmod",
                        lambda self, mode, **kw: asked.append(self.name))

    assert engine.make_runnable(root) == 0
    assert asked == []


def test_windows_is_not_touched(tmp_path, monkeypatch):
    """There is no executable bit to restore, and `chmod` on Windows sets the
    ReadOnly attribute instead -- which `clear_readonly` exists to remove."""
    monkeypatch.setattr(engine.os, "name", "nt")
    root = tmp_path / "engine"
    root.mkdir()
    (root / "check.command").write_text("x", encoding="utf-8")

    assert engine.make_runnable(root) == 0
